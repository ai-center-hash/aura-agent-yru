"""HTTP client ของ Activity API (ดู docs/02-activity-api-reference.md)

มี 2 โหมดการยืนยันตัวตน เลือกด้วย `IDENTITY_MODE` ใน .env
- **passport** (ค่าเริ่มต้น): ถาม YRU Passport ว่า token เป็นของใคร → ได้รหัสนักศึกษา →
  เรียก `/summary/user/{รหัส}` ซึ่งเป็น public route · **ไม่ส่ง token ของ Passport ให้ Activity API**
  ใช้โหมดนี้เพราะ Activity API ไม่รับ token ของ Passport (Q1 ใน HANDOFF)
- **activity_me**: ส่ง token ตรงไปที่ `/summary/me` (ใช้เมื่อเจ้าของ API รับ token ได้แล้ว)

ทั้งสองโหมด ตัวตนมาจาก token เสมอ ไม่ได้มาจากข้อความที่ผู้ใช้พิมพ์

หลักการอื่น
- ทุก method รับ `jwt` เป็น argument ไม่เก็บไว้ใน instance และไม่ log
- cache แยกตามผู้ใช้ด้วย fingerprint ของ token (ดู `cache.make_cache_key`) ยกเว้นข้อมูล public
"""

import logging
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from ..config import Settings, get_settings
from .cache import Cache, MemoryCache, make_cache_key
from .errors import NoActivityFrame, UpstreamSchemaError
from .http import JsonApi
from .passport import PassportClient
from .schemas import PassportUser, Registration, Schedule, StudentSummary

logger = logging.getLogger(__name__)

SUMMARY_PATH = "/v1/report/summary/me"
SUMMARY_USER_PATH = "/v1/report/summary/user"
SUMMARY_USER_LABEL = "/v1/report/summary/user/{student}"  # ใช้ใน log/error แทนรหัสจริง
SCHEDULES_PATH = "/v1/act/activity-schedules"
REGISTRATIONS_PATH = "/v1/act/act-registrations"

SUMMARY_TTL_S = 120.0
SCHEDULES_TTL_S = 120.0
REGISTRATIONS_TTL_S = 60.0

PUBLIC_SCOPE = "public"  # ข้อมูลที่เหมือนกันทุกคน จึงใช้ cache ร่วมกันได้

_SCHEDULE_LIST = TypeAdapter(list[Schedule])
_REGISTRATION_LIST = TypeAdapter(list[Registration])

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
    ) -> None:
        super().__init__(base_url, timeout_s, retry_delay_s=retry_delay_s)
        self._cache: Cache = cache if cache is not None else MemoryCache()
        self._passport = passport

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
        """
        if self._passport is None:
            payload = await self._get_json(
                SUMMARY_PATH, {}, auth=jwt, cache_scope=jwt, ttl_s=SUMMARY_TTL_S
            )
            return self._summary_of(payload, SUMMARY_PATH, identity=None)

        identity = await self._passport.get_identity(jwt)
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
        settings.act_api_base_url, settings.act_api_timeout_s, shared_cache, passport=passport
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
