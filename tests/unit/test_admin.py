"""ผู้ดูแลระบบกิจกรรมดูนักศึกษาได้ทุกรหัส (ตัดสิน 2026-10-29)

ผู้ดูแลระบบ = บุคลากรใน Passport (`user_type="staff"`) ที่มีบัญชีในระบบกิจกรรมตรงทั้ง username และ
`type_ref_id` = `user_type_id` พร้อม role `admin` (เว็บ act.yru.ac.th ใช้ `local-role:admin` แบบเดียวกัน)
หรือ username ที่อยู่ใน `DEV_ADMIN_USERNAMES` · ข้อมูลทั้งหมดเป็นค่าสมมติ mock HTTP ด้วย respx
"""

import logging

import httpx
import pytest

from aura_agent.data import (
    ActClient,
    NotAnAdmin,
    NotYourAdvisee,
    PassportClient,
    UpstreamNotFound,
    UpstreamRejected,
)
from aura_agent.data.act_client import SUMMARY_USER_PATH, USERS_PATH
from aura_agent.data.passport import USERINFO_PATH
from aura_agent.data.schemas import PassportUser
from aura_agent.processing import StudentProfile
from aura_agent.tools import get_advisee_progress
from aura_agent.tools.advisees import NOT_ADVISEE_MESSAGE, NOT_FOUND_MESSAGE

from .conftest import BASE_URL, JWT

PASSPORT_URL = "https://passport.test"
USERINFO_URL = f"{PASSPORT_URL}{USERINFO_PATH}"
USERS_URL = f"{BASE_URL}{USERS_PATH}"
SUMMARY_URL = f"{BASE_URL}{SUMMARY_USER_PATH}"
ADMIN_REF = "2001"
ADMIN_INFO = {
    "sub": 30003,
    "username": "admin.a",
    "user_type": "staff",
    "user_type_id": ADMIN_REF,
    "position_name": "เจ้าหน้าที่",
    "display_name": "เจ้าหน้าที่ทดสอบ ระบบ",
}
OTHER_CODE = "406600399"


def staff_row(username: str, ref: str, roles: list[str], type_: str = "personnel") -> dict:
    """แถวบุคลากรจาก /v1/auth/users แบบเดียวกับของจริง รวมฟิลด์ส่วนตัวที่ต้องถูกทิ้ง"""
    return {
        "id": int(ref),
        "username": username,
        "type": type_,
        "type_ref_id": int(ref),
        "email": f"{username}@example.test",
        "telephone": "0800000000",
        "address": "บ้านเลขที่สมมติ",
        "roles": [{"name": role, "display_name": role.title()} for role in roles],
        "permissions": [{"name": "manage-users"}] if "admin" in roles else [],
    }


STAFF_ROWS = [
    staff_row("admin.a", ADMIN_REF, ["admin"]),
    staff_row("plain.p", "2002", []),
    staff_row("advisor.t", "1577", ["advisor"], type_="teacher"),
]


@pytest.fixture
async def make_client(cache):
    clients: list[ActClient] = []

    def _make(**kwargs) -> ActClient:
        passport = PassportClient(PASSPORT_URL, timeout_s=1.0, cache=cache, retry_delay_s=0)
        client = ActClient(
            BASE_URL, timeout_s=1.0, cache=cache, passport=passport, retry_delay_s=0, **kwargs
        )
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


def mock_userinfo(respx_mock, **override):
    info = {**ADMIN_INFO, **override}
    return respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=info))


def mock_staff(respx_mock, rows=STAFF_ROWS):
    return respx_mock.get(USERS_URL, params={"type_in": "teacher,staff,personnel"}).mock(
        return_value=httpx.Response(200, json={"data": rows})
    )


# ---- ใครเป็นผู้ดูแลระบบ ----


async def test_activity_admin_is_admin(make_client, respx_mock):
    mock_userinfo(respx_mock)
    route = mock_staff(respx_mock)

    assert await make_client().is_admin(JWT) is True
    assert "authorization" not in route.calls.last.request.headers  # token ของ Passport ไม่ถูกส่งต่อ


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"username": "plain.p", "user_type_id": "2002"}, "บุคลากรที่ไม่มี role admin"),
        ({"user_type_id": "9999"}, "username ตรงแต่ type_ref_id ไม่ตรง"),
        ({"username": "someone.else"}, "type_ref_id ตรงแต่ username ไม่ตรง"),
        ({"user_type": "student_assistant"}, "user_type ที่ไม่รู้จัก ไม่ถือว่าเป็นบุคลากร"),
        ({"user_type_id": None}, "ไม่มี user_type_id"),
    ],
)
async def test_not_admin(make_client, respx_mock, override, reason):
    mock_userinfo(respx_mock, **override)
    mock_staff(respx_mock)

    assert await make_client().is_admin(JWT) is False, reason


async def test_student_is_never_admin_and_staff_list_is_not_fetched(make_client, respx_mock):
    mock_userinfo(respx_mock, user_type="student", username="406600101")
    route = mock_staff(respx_mock)

    assert await make_client(dev_admins=["406600101"]).is_admin(JWT) is False
    assert route.call_count == 0


async def test_admin_role_on_a_student_account_does_not_count(make_client, respx_mock):
    mock_userinfo(respx_mock)
    mock_staff(respx_mock, rows=[staff_row("admin.a", ADMIN_REF, ["admin"], type_="student")])

    assert await make_client().is_admin(JWT) is False


async def test_staff_list_is_cached_with_only_needed_fields(make_client, respx_mock, cache):
    mock_userinfo(respx_mock)
    route = mock_staff(respx_mock)
    client = make_client()

    assert await client.is_admin(JWT) is True
    assert await client.is_admin(JWT) is True

    assert route.call_count == 1
    stored = str([entry.value for entry in cache._cache.values()])
    assert "telephone" not in stored and "example.test" not in stored


async def test_dev_admin_from_settings(make_client, respx_mock):
    mock_userinfo(respx_mock, username="Dev.Person", user_type_id="7777")
    route = mock_staff(respx_mock)

    assert await make_client(dev_admins=["dev.person"]).is_admin(JWT) is True
    assert route.call_count == 0  # ไม่ต้องถามระบบกิจกรรม


async def test_dev_admins_is_empty_by_default(make_client, respx_mock):
    mock_userinfo(respx_mock, username="dev.person", user_type_id="7777")
    mock_staff(respx_mock)

    assert await make_client().is_admin(JWT) is False


def test_dev_admin_setting_is_parsed(monkeypatch):
    """ไม่อ่าน .env ของเครื่อง (เครื่องผู้พัฒนาอาจตั้งค่านี้ไว้)"""
    from aura_agent.config import Settings

    monkeypatch.delenv("DEV_ADMIN_USERNAMES", raising=False)
    assert Settings(_env_file=None, service_key="x" * 32).dev_admins == frozenset()

    monkeypatch.setenv("DEV_ADMIN_USERNAMES", " Amornthep.Muk , other.x ,, ")
    assert Settings(_env_file=None, service_key="x" * 32).dev_admins == {"amornthep.muk", "other.x"}


# ---- ดูข้อมูลด้วยสิทธิ์ผู้ดูแลระบบ ----


async def test_admin_reads_any_student(make_client, respx_mock, load_fixture):
    mock_userinfo(respx_mock)
    mock_staff(respx_mock)
    summary_route = respx_mock.get(f"{SUMMARY_URL}/{OTHER_CODE}").mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    student, summary = await make_client().get_student_summary_as_admin(JWT, f" {OTHER_CODE} ")

    assert student.username == OTHER_CODE
    assert summary.categories
    assert "authorization" not in summary_route.calls.last.request.headers


async def test_non_admin_cannot_read_and_summary_is_not_requested(make_client, respx_mock):
    mock_userinfo(respx_mock, username="plain.p", user_type_id="2002")
    mock_staff(respx_mock)
    summary_route = respx_mock.get(url__startswith=f"{SUMMARY_URL}/")

    with pytest.raises(NotAnAdmin):
        await make_client().get_student_summary_as_admin(JWT, OTHER_CODE)

    assert summary_route.call_count == 0


async def test_unknown_student_code_is_not_found(make_client, respx_mock):
    mock_userinfo(respx_mock)
    mock_staff(respx_mock)
    respx_mock.get(f"{SUMMARY_URL}/406699999").mock(
        return_value=httpx.Response(404, json={"success": False, "message": "ไม่พบผู้ใช้ที่ระบุ"})
    )

    with pytest.raises(UpstreamNotFound) as raised:
        await make_client().get_student_summary_as_admin(JWT, "406699999")

    assert isinstance(raised.value, UpstreamRejected)  # ที่เดิมจับ UpstreamRejected ยังทำงานเหมือนเดิม
    assert "406699999" not in str(raised.value)  # error ใช้ label ไม่มีรหัส


async def test_admin_view_is_audited_without_raw_ids(make_client, respx_mock, load_fixture, caplog):
    mock_userinfo(respx_mock)
    mock_staff(respx_mock)
    respx_mock.get(f"{SUMMARY_URL}/{OTHER_CODE}").mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    with caplog.at_level(logging.INFO, logger="aura_agent.audit"):
        await make_client(audit_key=b"k" * 32).get_student_summary_as_admin(JWT, OTHER_CODE)

    audit = [record.getMessage() for record in caplog.records if record.name == "aura_agent.audit"]
    assert len(audit) == 1 and audit[0].startswith("admin_view by=")
    assert OTHER_CODE not in audit[0] and "30003" not in audit[0]


async def test_audit_id_is_stable_for_the_same_key(make_client):
    first = make_client(audit_key=b"k" * 32)
    second = make_client(audit_key=b"k" * 32)
    other = make_client(audit_key=b"x" * 32)

    assert first._audit_id(OTHER_CODE) == second._audit_id(OTHER_CODE)
    assert first._audit_id(OTHER_CODE) != other._audit_id(OTHER_CODE)


# ---- ปิดช่อง "ไม่ใช่นักศึกษา = บุคลากร" ----


async def test_unknown_user_type_has_no_advisees(make_client, respx_mock):
    """`user_type` ที่ไม่ใช่ student และไม่ใช่ staff ต้องไม่ได้รายชื่อใคร แม้ user_type_id จะชนกับอาจารย์"""
    mock_userinfo(respx_mock, user_type="student_assistant", user_type_id="1577")
    route = respx_mock.get(USERS_URL)

    assert await make_client().get_advisees(JWT) == []
    with pytest.raises(NotYourAdvisee):
        await make_client().get_advisee_summary(JWT, OTHER_CODE)
    assert route.call_count == 0


def test_passport_staff_flag():
    assert PassportUser.model_validate(ADMIN_INFO).is_staff is True
    assert PassportUser.model_validate({**ADMIN_INFO, "user_type": "student"}).is_staff is False
    assert PassportUser.model_validate({**ADMIN_INFO, "user_type": "other"}).is_staff is False


# ---- tool ----


ADMIN = StudentProfile.from_passport(PassportUser.model_validate(ADMIN_INFO))


class FakeAdminClient:
    """ActClient ปลอม: ไม่มีนักศึกษาในที่ปรึกษา และเป็น/ไม่เป็นผู้ดูแลระบบตาม `admin`"""

    def __init__(self, summary, *, admin: bool) -> None:
        self.summary = summary
        self.admin = admin
        self.calls: list[str] = []

    async def get_advisee_summary(self, jwt, code):
        self.calls.append("get_advisee_summary")
        raise NotYourAdvisee("x")

    async def is_admin(self, jwt):
        self.calls.append("is_admin")
        return self.admin

    async def get_student_summary_as_admin(self, jwt, code):
        from aura_agent.data.schemas import Advisee

        self.calls.append("get_student_summary_as_admin")
        if not self.admin:
            raise NotAnAdmin("x")
        if code == "406699999":
            raise UpstreamNotFound("x: HTTP 404")
        return Advisee(username=code, name="นักศึกษา สมมติ"), self.summary


@pytest.fixture
def install(summary):
    from aura_agent.data import set_act_client

    def _install(*, admin: bool) -> FakeAdminClient:
        fake = FakeAdminClient(summary, admin=admin)
        set_act_client(fake)
        return fake

    yield _install
    set_act_client(None)


async def test_tool_lets_admin_see_any_student(install, tool_config):
    fake = install(admin=True)

    text = await get_advisee_progress.ainvoke(
        {"student_code": OTHER_CODE, "state": {"student": ADMIN}}, tool_config
    )

    assert text.startswith(f"[ความคืบหน้าของนักศึกษา (ดูด้วยสิทธิ์ผู้ดูแลระบบ)] {OTHER_CODE} ")
    assert "[ความคืบหน้า]" in text
    assert fake.calls == ["get_advisee_summary", "is_admin", "get_student_summary_as_admin"]


async def test_tool_refuses_non_admin_staff(install, tool_config):
    fake = install(admin=False)

    text = await get_advisee_progress.ainvoke(
        {"student_code": OTHER_CODE, "state": {"student": ADMIN}}, tool_config
    )

    assert text == NOT_ADVISEE_MESSAGE.format(code=OTHER_CODE)
    assert "get_student_summary_as_admin" not in fake.calls


async def test_tool_reports_unknown_code(install, tool_config):
    install(admin=True)

    text = await get_advisee_progress.ainvoke(
        {"student_code": "406699999", "state": {"student": ADMIN}}, tool_config
    )

    assert text == NOT_FOUND_MESSAGE.format(code="406699999")


async def test_tool_still_refuses_students_before_any_call(install, tool_config, student):
    fake = install(admin=True)

    text = await get_advisee_progress.ainvoke(
        {"student_code": OTHER_CODE, "state": {"student": student}}, tool_config
    )

    assert text.startswith("ส่วนนี้ใช้ได้เฉพาะอาจารย์ที่ปรึกษา")
    assert fake.calls == []
