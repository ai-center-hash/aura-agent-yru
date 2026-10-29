"""HTTP client ของ Activity API (ดู docs/02-activity-api-reference.md)

มี 2 โหมดการยืนยันตัวตน เลือกด้วย `IDENTITY_MODE` ใน .env
- **passport** (ค่าเริ่มต้น): ถาม YRU Passport ว่า token เป็นของใคร → ได้รหัสนักศึกษา →
  เรียก `/summary/user/{รหัส}` ซึ่งเป็น public route · **ไม่ส่ง token ของ Passport ให้ Activity API**
  ใช้โหมดนี้เพราะ Activity API ไม่รับ token ของ Passport (Q1 ใน HANDOFF)
- **activity_me**: ส่ง token ตรงไปที่ `/summary/me` (ใช้เมื่อเจ้าของ API รับ token ได้แล้ว)

ทั้งสองโหมด ตัวตนมาจาก token เสมอ ไม่ได้มาจากข้อความที่ผู้ใช้พิมพ์

สิทธิ์ดูข้อมูลนักศึกษาคนอื่น (โหมด passport เท่านั้น · บุคลากรต้องมี Passport `user_type="staff"`)
- อาจารย์ที่ปรึกษา: เฉพาะนักศึกษาที่ `advisor_type_ref_id` = `user_type_id` ของตัวเอง
- ผู้ดูแลระบบ: role `admin` ในระบบกิจกรรม (ตรงกับ `local-role:admin` ของเว็บ act.yru.ac.th) ดูได้ทุกรหัส
  หรือ username ที่อยู่ใน `DEV_ADMIN_USERNAMES` (ใช้ตอนพัฒนาเท่านั้น) · ทุกครั้งบันทึก audit log

หลักการอื่น
- ทุก method รับ `jwt` เป็น argument ไม่เก็บไว้ใน instance และไม่ log
- cache แยกตามผู้ใช้ด้วย fingerprint ของ token (ดู `cache.make_cache_key`) ยกเว้นข้อมูล public
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from ..config import Settings, get_settings
from .cache import Cache, MemoryCache, make_cache_key
from .errors import NoActivityFrame, NotAnAdmin, NotAStudent, NotYourAdvisee, UpstreamSchemaError
from .http import JsonApi
from .passport import PassportClient
from .schemas import (
    Advisee,
    PassportUser,
    Registration,
    Schedule,
    StaffAccount,
    StudentSummary,
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("aura_agent.audit")

SUMMARY_PATH = "/v1/report/summary/me"
SUMMARY_USER_PATH = "/v1/report/summary/user"
SUMMARY_USER_LABEL = "/v1/report/summary/user/{student}"  # ใช้ใน log/error แทนรหัสจริง
SCHEDULES_PATH = "/v1/act/activity-schedules"
REGISTRATIONS_PATH = "/v1/act/act-registrations"
USERS_PATH = "/v1/auth/users"
ADVISEES_LABEL = "/v1/auth/users?advisor={advisor}"  # ใช้ใน log/error แทนรหัสอาจารย์
STAFF_LABEL = "/v1/auth/users?type_in=staff"
# type ของบุคลากรในระบบกิจกรรม (คนละชุดกับ user_type ของ Passport)
STAFF_TYPES = ("teacher", "staff", "personnel")
ADMIN_ROLE = "admin"

SUMMARY_TTL_S = 120.0
SCHEDULES_TTL_S = 120.0
REGISTRATIONS_TTL_S = 60.0
ADVISEES_TTL_S = 300.0
STAFF_TTL_S = 300.0  # เพิ่ม/ถอด role admin ในระบบกิจกรรมแล้วมีผลกับบอทภายใน 5 นาที
AUDIT_ID_LEN = 12

PUBLIC_SCOPE = "public"  # ข้อมูลที่เหมือนกันทุกคน จึงใช้ cache ร่วมกันได้

_SCHEDULE_LIST = TypeAdapter(list[Schedule])
_REGISTRATION_LIST = TypeAdapter(list[Registration])
_ADVISEE_LIST = TypeAdapter(list[Advisee])
_STAFF_LIST = TypeAdapter(list[StaffAccount])

RegistrationPhase = Literal["open", "upcoming"]


class ActClient(JsonApi):
    """อ่านข้อมูลจาก Activity API แล้วคืน Pydantic object"""

    service_name = "act_client"

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 15.0,
        cache: Cache | None = None,
        *,
        passport: PassportClient | None = None,
        retry_delay_s: float = 0.25,
        dev_admins: Iterable[str] = (),
        audit_key: bytes | None = None,
    ) -> None:
        super().__init__(base_url, timeout_s, retry_delay_s=retry_delay_s)
        self._cache: Cache = cache if cache is not None else MemoryCache()
        self._passport = passport
        self._dev_admins = frozenset(name.strip().lower() for name in dev_admins if name.strip())
        # ไม่ส่ง key มา (test) ใช้ key สุ่มต่อ process · ของจริงใช้ SERVICE_KEY ให้ id คงที่ข้ามการ restart
        self._audit_key = audit_key or secrets.token_bytes(32)

    @property
    def identity_mode(self) -> str:
        return "passport" if self._passport is not None else "activity_me"

    async def aclose(self) -> None:
        await super().aclose()
        if self._passport is not None:
            await self._passport.aclose()

    # ---- ตัวตน ----

    async def get_subject(self, jwt: str) -> str:
        """id ถาวรของผู้ใช้ ใช้แยกประวัติแชท (ได้แม้นักศึกษายังไม่มีกรอบกิจกรรม)"""
        if self._passport is not None:
            identity = await self._passport.get_identity(jwt)
            return f"passport:{identity.sub}"
        return str((await self.get_my_summary(jwt)).user.id)

    async def get_identity(self, jwt: str) -> PassportUser | None:
        """ตัวตนจาก Passport (โหมด activity_me ไม่มีข้อมูลนี้ จึงคืน None)"""
        if self._passport is None:
            return None
        return await self._passport.get_identity(jwt)

    # ---- ความคืบหน้า ----

    async def get_my_summary(self, jwt: str) -> StudentSummary:
        """ความคืบหน้ากิจกรรมของเจ้าของ token (`user.id` ที่ได้คือ user_id ที่เชื่อถือได้)

        นักศึกษาที่ยังไม่มีกรอบกิจกรรมจะได้ `NoActivityFrame`
        บุคลากร (โหมด passport) จะได้ `NotAStudent` โดยไม่เรียก Activity API
        เพราะ username ของบุคลากรไม่ใช่รหัสนักศึกษา
        """
        if self._passport is None:
            payload = await self._get_json(
                SUMMARY_PATH, {}, auth=jwt, cache_scope=jwt, ttl_s=SUMMARY_TTL_S
            )
            return self._summary_of(payload, SUMMARY_PATH, identity=None)

        identity = await self._passport.get_identity(jwt)
        if not identity.is_student:
            raise NotAStudent(f"user_type={identity.user_type}", identity=identity)
        payload = await self._get_json(
            f"{SUMMARY_USER_PATH}/{quote(identity.student_code or '', safe='')}",
            {},
            auth=None,
            cache_scope=jwt,
            ttl_s=SUMMARY_TTL_S,
            label=SUMMARY_USER_LABEL,
        )
        return self._summary_of(payload, SUMMARY_USER_LABEL, identity=identity)

    # ---- รอบกิจกรรม ----

    async def get_schedules(
        self,
        jwt: str,
        *,
        phase: RegistrationPhase | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
    ) -> list[Schedule]:
        """รอบกิจกรรมที่เผยแพร่แล้ว เรียงตามวันเปิดรับสมัครจากเก่าไปใหม่"""
        params: dict[str, str] = {
            "paginate": "false",
            "is_published": "true",
            "sort_by": "registration_start_date",
            "sort_order": "asc",
        }
        if phase is not None:
            params["registration_phase"] = phase
        if date_from is not None:
            params["activity_date_from"] = date_from.isoformat()
        if date_to is not None:
            params["activity_date_to"] = date_to.isoformat()
        if search and search.strip():
            params["search"] = search.strip()

        auth = self._forwarded(jwt)
        payload = await self._get_json(
            SCHEDULES_PATH,
            params,
            auth=auth,
            cache_scope=jwt if auth else PUBLIC_SCOPE,
            ttl_s=SCHEDULES_TTL_S,
        )
        data = self._unwrap(payload, SCHEDULES_PATH, list)
        return self._validate(_SCHEDULE_LIST.validate_python, data, SCHEDULES_PATH)

    # ---- ประวัติการลงทะเบียน ----

    async def get_registrations(self, jwt: str, user_id: int) -> list[Registration]:
        """ประวัติการลงทะเบียนของ user_id เรียงจากที่ลงทะเบียนล่าสุด

        ชั้นนี้ไม่รู้ว่า user_id มาจากไหน **ผู้เรียก (tool) ต้องส่งค่าที่ได้จาก
        get_my_summary() เท่านั้น** ห้ามส่งค่าที่ผู้ใช้พิมพ์มา
        """
        params = {
            "paginate": "false",
            "user_id": str(user_id),
            "sort_by": "registered_at",
            "sort_order": "desc",
        }
        payload = await self._get_json(
            REGISTRATIONS_PATH,
            params,
            auth=self._forwarded(jwt),
            cache_scope=jwt,
            ttl_s=REGISTRATIONS_TTL_S,
        )
        data = self._unwrap(payload, REGISTRATIONS_PATH, list)
        return self._validate(_REGISTRATION_LIST.validate_python, data, REGISTRATIONS_PATH)

    # ---- นักศึกษาในที่ปรึกษา (อาจารย์) ----

    async def get_advisees(self, jwt: str) -> list[Advisee]:
        """นักศึกษาในที่ปรึกษาของเจ้าของ token เรียงตามรหัส (ไม่ใช่อาจารย์ที่ปรึกษาจะได้ list ว่าง)

        อาจารย์ระบุจาก `user_type_id` ใน Passport ของเจ้าของ token เท่านั้น (ไม่รับจากข้อความผู้ใช้)
        แล้วให้ Activity API กรองด้วย `advisor_type_ref_id` · **กรองซ้ำฝั่งเรา** เผื่อ API เมินพารามิเตอร์
        (เคยเจอกับ `advisor_username` ที่ถูกเมินแล้วได้นักศึกษาทั้งมหาวิทยาลัย)
        เก็บใน cache เฉพาะฟิลด์ของ `Advisee` ไม่เก็บ response ดิบที่มีที่อยู่/เบอร์โทร
        """
        identity = await self.get_identity(jwt)
        if identity is None or not identity.is_staff or not identity.user_type_id:
            return []

        advisor = identity.user_type_id
        key = make_cache_key(ADVISEES_LABEL, {"advisor": advisor}, jwt)
        cached = await self._cache.get(key)
        if cached is not None:
            return self._validate(_ADVISEE_LIST.validate_python, cached, ADVISEES_LABEL)

        params = {
            "paginate": "false",
            "type": "student",
            "advisor_type_ref_id": advisor,
            "include_activity_summary": "1",
            "sort_by": "username",
            "sort_order": "asc",
        }
        payload = await self._fetch(
            USERS_PATH, params, auth=self._forwarded(jwt), label=ADVISEES_LABEL
        )
        rows = self._validate(
            _ADVISEE_LIST.validate_python,
            self._unwrap(payload, ADVISEES_LABEL, list),
            ADVISEES_LABEL,
        )
        advisees = [row for row in rows if row.advisor_type_ref_id == advisor]
        if len(advisees) != len(rows):
            logger.warning(
                "act_client path=%s dropped=%d (not this advisor)",
                ADVISEES_LABEL,
                len(rows) - len(advisees),
            )
        await self._cache.set(key, [row.model_dump() for row in advisees], ADVISEES_TTL_S)
        return advisees

    async def get_advisee_summary(
        self, jwt: str, student_code: str
    ) -> tuple[Advisee, StudentSummary]:
        """ความคืบหน้าของนักศึกษา 1 คน **เฉพาะเมื่ออยู่ในที่ปรึกษาของเจ้าของ token**

        รหัสนักศึกษามาจากข้อความของผู้ใช้ได้ เพราะตรวจกับรายชื่อจาก `get_advisees()` ทุกครั้ง
        ไม่อยู่ในรายชื่อ → `NotYourAdvisee` โดยไม่เรียก summary ของรหัสนั้นเลย
        """
        code = student_code.strip()
        advisee = next((row for row in await self.get_advisees(jwt) if row.username == code), None)
        if advisee is None:
            raise NotYourAdvisee("รหัสที่ขอไม่อยู่ในรายชื่อที่ปรึกษา")

        payload = await self._get_json(
            f"{SUMMARY_USER_PATH}/{quote(code, safe='')}",
            {},
            auth=None,
            cache_scope=f"advisee:{code}",
            ttl_s=SUMMARY_TTL_S,
            label=SUMMARY_USER_LABEL,
        )
        return advisee, self._summary_of(payload, SUMMARY_USER_LABEL, identity=None)

    # ---- ผู้ดูแลระบบ ----

    async def is_admin(self, jwt: str) -> bool:
        """เจ้าของ token เป็นผู้ดูแลระบบกิจกรรมไหม (ไม่แน่ใจ = ไม่ใช่)

        ต้องเป็นบุคลากรใน Passport และมีบัญชีในระบบกิจกรรมที่ตรงทั้ง username และ
        `type_ref_id` = `user_type_id` พร้อม role `admin` · หรืออยู่ใน `DEV_ADMIN_USERNAMES`
        """
        identity = await self.get_identity(jwt)
        if identity is None or identity.is_student or not identity.login:
            return False
        login = identity.login.lower()
        if login in self._dev_admins:
            return True
        if not identity.is_staff or not identity.user_type_id:
            return False

        accounts = await self._staff_accounts()
        account = next((row for row in accounts if row.username.lower() == login), None)
        return (
            account is not None
            and account.type in STAFF_TYPES
            and account.type_ref_id == identity.user_type_id
            and ADMIN_ROLE in account.roles
        )

    async def get_student_summary_as_admin(
        self, jwt: str, student_code: str
    ) -> tuple[Advisee, StudentSummary]:
        """ความคืบหน้าของนักศึกษารหัสใดก็ได้ **เฉพาะผู้ดูแลระบบ** (ตรวจ `is_admin` ทุกครั้ง)

        ไม่ใช่ผู้ดูแลระบบ → `NotAnAdmin` โดยไม่เรียก summary · รหัสไม่มีในระบบ → `UpstreamNotFound`
        บันทึก audit log ว่าใครดูใคร ด้วย id ที่ hash ด้วย key ลับ (ไม่ log รหัสนักศึกษาตรงๆ)
        """
        if not await self.is_admin(jwt):
            raise NotAnAdmin("ไม่มี role admin ในระบบกิจกรรม")

        code = student_code.strip()
        identity = await self.get_identity(jwt)
        audit_logger.info(
            "admin_view by=%s student=%s",
            self._audit_id(identity.sub if identity else "?"),
            self._audit_id(code),
        )
        payload = await self._get_json(
            f"{SUMMARY_USER_PATH}/{quote(code, safe='')}",
            {},
            auth=None,
            cache_scope=f"advisee:{code}",
            ttl_s=SUMMARY_TTL_S,
            label=SUMMARY_USER_LABEL,
        )
        summary = self._summary_of(payload, SUMMARY_USER_LABEL, identity=None)
        user = summary.user
        student = Advisee(
            username=code, name=user.name, program=user.major, student_status=user.student_status
        )
        return student, summary

    async def _staff_accounts(self) -> list[StaffAccount]:
        """บุคลากรทั้งหมดในระบบกิจกรรม (~30 คน) · cache เฉพาะฟิลด์ใน `StaffAccount`

        `username=` ของ API ถูกเมิน จึงดึงทั้งกลุ่มด้วย `type_in` แล้วจับคู่เองฝั่งเรา
        """
        key = make_cache_key(STAFF_LABEL, {}, PUBLIC_SCOPE)
        cached = await self._cache.get(key)
        if cached is not None:
            return self._validate(_STAFF_LIST.validate_python, cached, STAFF_LABEL)

        params = {"paginate": "false", "type_in": ",".join(STAFF_TYPES)}
        payload = await self._fetch(USERS_PATH, params, auth=None, label=STAFF_LABEL)
        rows = self._validate(
            _STAFF_LIST.validate_python, self._unwrap(payload, STAFF_LABEL, list), STAFF_LABEL
        )
        await self._cache.set(key, [row.model_dump() for row in rows], STAFF_TTL_S)
        return rows

    def _audit_id(self, value: str) -> str:
        """id ใน audit log · ย้อนเป็นค่าจริงไม่ได้ถ้าไม่มี key (hash เฉยๆ เดารหัส 9 หลักกลับได้)"""
        digest = hmac.new(self._audit_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
        return digest[:AUDIT_ID_LEN]

    # ---- health check ----

    async def ping(self) -> bool:
        """เช็คว่า Activity API ตอบอยู่ไหม (ใช้ใน GET /v1/health) ไม่โยน exception

        ยิงแบบแบ่งหน้าเอา 1 แถว เพื่อไม่ให้ server ต้อง stream ข้อมูลทั้งหมด
        สถานะ 4xx ก็ถือว่าเซิร์ฟเวอร์ยังตอบอยู่ (เพราะเราไม่ได้ส่ง token ไปด้วย)
        """
        try:
            response = await self._client.get(
                SCHEDULES_PATH, params={"paginate": "true", "per_page": "1"}
            )
        except httpx.HTTPError as exc:
            logger.warning("act_client ping failed error=%s", type(exc).__name__)
            return False
        return response.status_code < 500

    # ---- ภายใน ----

    def _forwarded(self, jwt: str) -> str | None:
        """ส่ง token ต่อให้ Activity API เฉพาะโหมด activity_me (โหมด passport token เป็นของ Passport)"""
        return jwt if self._passport is None else None

    async def _get_json(
        self,
        path: str,
        params: dict[str, str],
        *,
        auth: str | None,
        cache_scope: str,
        ttl_s: float,
        label: str | None = None,
    ) -> Any:
        label = label or path
        key = make_cache_key(label, params, cache_scope)
        cached = await self._cache.get(key)
        if cached is not None:
            logger.debug("act_client path=%s cache=hit", label)
            return cached

        payload = await self._fetch(path, params, auth=auth, label=label)
        await self._cache.set(key, payload, ttl_s)
        return payload

    def _summary_of(
        self, payload: Any, label: str, *, identity: PassportUser | None
    ) -> StudentSummary:
        if isinstance(payload, dict) and payload.get("no_frame"):
            raise NoActivityFrame(str(payload.get("message") or ""), identity=identity)
        data = self._unwrap(payload, label, dict)
        return self._validate(StudentSummary.model_validate, data, label)

    @staticmethod
    def _unwrap(payload: Any, path: str, expected: type) -> Any:
        """ดึงค่าใน key data ออกมา (streamed JSON และ response object ใช้ key นี้เหมือนกัน)"""
        if not isinstance(payload, dict) or "data" not in payload:
            raise UpstreamSchemaError(f"{path}: response ไม่มี key data")
        data = payload["data"]
        if not isinstance(data, expected):
            raise UpstreamSchemaError(
                f"{path}: data ควรเป็น {expected.__name__} แต่ได้ {type(data).__name__}"
            )
        return data

    @staticmethod
    def _validate(validator: Any, data: Any, path: str) -> Any:
        """แปลงเป็น Pydantic object และแปลง ValidationError เป็น UpstreamSchemaError

        ใส่แค่ชื่อฟิลด์ที่ผิดลงใน error ไม่ใส่ค่าที่ได้มา เพราะค่าอาจเป็นข้อมูลส่วนบุคคล
        """
        try:
            return validator(data)
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(str(part) for part in error["loc"]) for error in exc.errors()[:5]
            )
            raise UpstreamSchemaError(
                f"{path}: ฟิลด์ไม่ตรง schema ({exc.error_count()} จุด) {fields}"
            ) from exc


def build_act_client(settings: Settings | None = None, *, cache: Cache | None = None) -> ActClient:
    """สร้าง ActClient ตาม `IDENTITY_MODE` ใน .env (ใช้ใน lifespan ของ API, CLI และ script)"""
    settings = settings or get_settings()
    shared_cache = cache if cache is not None else MemoryCache()
    passport = None
    if settings.identity_mode == "passport":
        passport = PassportClient(
            settings.passport_base_url, settings.passport_timeout_s, shared_cache
        )
    return ActClient(
        settings.act_api_base_url,
        settings.act_api_timeout_s,
        shared_cache,
        passport=passport,
        dev_admins=settings.dev_admins,
        audit_key=settings.service_key.get_secret_value().encode("utf-8"),
    )


_shared_client: ActClient | None = None


def get_act_client() -> ActClient:
    """client ตัวเดียวของแอป สร้างครั้งแรกที่เรียกโดยอ่านค่าจาก settings"""
    global _shared_client
    if _shared_client is None:
        _shared_client = build_act_client()
    return _shared_client


def set_act_client(client: ActClient | None) -> None:
    """ตั้ง client ที่ใช้ร่วมกัน ใช้ใน lifespan ของ API และใน test

    การตั้งค่าใหม่ไม่ปิด client ตัวเดิม ผู้เรียกต้อง `aclose()` เอง
    """
    global _shared_client
    _shared_client = client


async def close_act_client() -> None:
    """ปิด client ตอนแอปหยุดทำงาน (เรียกใน lifespan ของ FastAPI)"""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None
