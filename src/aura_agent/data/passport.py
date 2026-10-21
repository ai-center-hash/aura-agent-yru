"""ยืนยันตัวตนผู้ใช้ด้วย YRU Passport (OpenID Connect)

เอา access token ของผู้ใช้ไปเรียก `/oidc/userinfo` — Passport เป็นผู้ตรวจว่า token ยังใช้ได้
(หมดอายุหรือถูกเพิกถอนจะได้ 401) เราจึงไม่ต้องตรวจลายเซ็น JWT เอง และได้รหัสนักศึกษา
ที่เชื่อถือได้กลับมา (มาจาก token ไม่ใช่จากที่ผู้ใช้พิมพ์)

**token ของ Passport ใช้คุยกับ Passport เท่านั้น ห้ามส่งต่อให้ระบบอื่น**
"""

from pydantic import ValidationError

from .cache import Cache, MemoryCache, make_cache_key
from .errors import NotAStudent, PassportUnavailable, UpstreamSchemaError
from .http import JsonApi
from .schemas import PassportUser

USERINFO_PATH = "/oidc/userinfo"
IDENTITY_TTL_S = 300.0  # ตัวตนไม่เปลี่ยนบ่อย แต่ไม่ cache นานเกินไปเผื่อ token ถูกเพิกถอน


class PassportClient(JsonApi):
    """อ่านตัวตนของเจ้าของ token จาก YRU Passport"""

    service_name = "passport"
    unavailable_error = PassportUnavailable

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 10.0,
        cache: Cache | None = None,
        *,
        retry_delay_s: float = 0.25,
    ) -> None:
        super().__init__(base_url, timeout_s, retry_delay_s=retry_delay_s)
        self._cache: Cache = cache if cache is not None else MemoryCache()

    async def get_identity(self, token: str) -> PassportUser:
        """ตัวตนของเจ้าของ token · ไม่ใช่นักศึกษาจะได้ `NotAStudent`"""
        key = make_cache_key(USERINFO_PATH, {}, token)
        payload = await self._cache.get(key)
        if payload is None:
            payload = await self._fetch(USERINFO_PATH, {}, auth=token, label=USERINFO_PATH)
            await self._cache.set(key, payload, IDENTITY_TTL_S)

        try:
            user = PassportUser.model_validate(payload)
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors()[:5])
            raise UpstreamSchemaError(f"{USERINFO_PATH}: ฟิลด์ไม่ตรง schema {fields}") from exc

        if not user.is_student:
            raise NotAStudent(f"{USERINFO_PATH}: user_type={user.user_type}")
        if not user.student_code:
            raise UpstreamSchemaError(f"{USERINFO_PATH}: ไม่มี username ของนักศึกษา")
        return user
