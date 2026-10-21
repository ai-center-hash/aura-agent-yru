"""test ของ PassportClient: อ่านตัวตนจาก /oidc/userinfo, แปลง error และ cache"""

import httpx
import pytest

from aura_agent.data import (
    MemoryCache,
    NotAStudent,
    PassportClient,
    PassportUnavailable,
    TokenExpired,
)
from aura_agent.data.errors import UpstreamSchemaError
from aura_agent.data.passport import IDENTITY_TTL_S, USERINFO_PATH

PASSPORT_URL = "https://passport.test"
USERINFO_URL = f"{PASSPORT_URL}{USERINFO_PATH}"
TOKEN = "passport.access.token"
OTHER_TOKEN = "passport.access.other"

# ข้อมูลสมมติ ไม่ใช่นักศึกษาจริง (รูปร่างตาม claim ที่ Passport ส่งจริง)
STUDENT_INFO = {
    "sub": 10001,
    "username": "406500001",
    "preferred_username": "406500001",
    "user_type": "student",
    "name": "นักศึกษาทดสอบ ระบบ",
    "display_name": "นักศึกษาทดสอบ ระบบ",
    "org_unit_1_name": "คณะวิทยาศาสตร์และเทคโนโลยี",
    "email": "test@example.invalid",
    "cid": "0000000000000",
}


@pytest.fixture
async def passport(clock):
    async with PassportClient(
        PASSPORT_URL, timeout_s=1.0, cache=MemoryCache(timer=clock), retry_delay_s=0
    ) as client:
        yield client


async def test_identity_from_userinfo(passport, respx_mock):
    route = respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=STUDENT_INFO))

    user = await passport.get_identity(TOKEN)

    assert user.sub == "10001"  # Passport ส่งเป็นตัวเลข ต้องกลายเป็น string
    assert user.student_code == "406500001"
    assert user.display == "นักศึกษาทดสอบ ระบบ"
    assert user.org_unit_1_name == "คณะวิทยาศาสตร์และเทคโนโลยี"
    assert user.is_student is True
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_identity_does_not_keep_sensitive_claims(passport, respx_mock):
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=STUDENT_INFO))

    user = await passport.get_identity(TOKEN)

    dumped = user.model_dump()
    assert "email" not in dumped
    assert "cid" not in dumped  # เลขบัตรประชาชน ไม่ต้องเก็บ


async def test_falls_back_to_preferred_username(passport, respx_mock):
    info = {**STUDENT_INFO, "username": None}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=info))

    assert (await passport.get_identity(TOKEN)).student_code == "406500001"


async def test_expired_token_raises_token_expired(passport, respx_mock):
    route = respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(TokenExpired):
        await passport.get_identity(TOKEN)

    assert route.call_count == 1  # 401 ไม่ยิงซ้ำ


async def test_staff_account_is_rejected(passport, respx_mock):
    staff = {**STUDENT_INFO, "user_type": "staff"}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=staff))

    with pytest.raises(NotAStudent) as error:
        await passport.get_identity(TOKEN)

    assert error.value.code == "NOT_STUDENT"
    assert "นักศึกษา" in error.value.message_th


async def test_student_without_username_is_schema_error(passport, respx_mock):
    info = {**STUDENT_INFO, "username": None, "preferred_username": None}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=info))

    with pytest.raises(UpstreamSchemaError):
        await passport.get_identity(TOKEN)


async def test_userinfo_without_sub_is_schema_error(passport, respx_mock):
    info = {key: value for key, value in STUDENT_INFO.items() if key != "sub"}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=info))

    with pytest.raises(UpstreamSchemaError) as error:
        await passport.get_identity(TOKEN)

    assert "นักศึกษาทดสอบ" not in str(error.value)  # ไม่ใส่ค่าที่ได้มาลงใน error


async def test_passport_down_raises_passport_unavailable(passport, respx_mock):
    route = respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(PassportUnavailable) as error:
        await passport.get_identity(TOKEN)

    assert route.call_count == 2  # ยิงใหม่ 1 ครั้ง
    assert error.value.code == "UPSTREAM_UNAVAILABLE"
    assert "Passport" in error.value.message_th


async def test_identity_is_cached_per_token(passport, respx_mock, clock):
    route = respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=STUDENT_INFO))

    await passport.get_identity(TOKEN)
    await passport.get_identity(TOKEN)
    assert route.call_count == 1

    await passport.get_identity(OTHER_TOKEN)
    assert route.call_count == 2  # token อื่นต้องถาม Passport ใหม่

    clock.advance(IDENTITY_TTL_S + 1)
    await passport.get_identity(TOKEN)
    assert route.call_count == 3  # หมดอายุ cache แล้ว
