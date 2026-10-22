"""อาจารย์ที่ปรึกษาดูนักศึกษาในที่ปรึกษาของตัวเอง (ขั้นที่ 2 · 2026-10-22)

ตัวผูก: `user_type_id` ใน Passport ของอาจารย์ = `advisor_type_ref_id` ของนักศึกษาใน `/v1/auth/users`
ข้อมูลทั้งหมดเป็นค่าสมมติ · mock HTTP ด้วย respx ไม่ยิง API จริง
"""

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import build_graph, run_config, state_serializer
from aura_agent.agent.prompts import render_system_prompt
from aura_agent.data import ActClient, NotYourAdvisee, PassportClient
from aura_agent.data.act_client import ADVISEES_LABEL, SUMMARY_USER_PATH, USERS_PATH
from aura_agent.data.passport import USERINFO_PATH
from aura_agent.data.schemas import Advisee, PassportUser
from aura_agent.processing import StudentProfile, format_advisees
from aura_agent.tools import get_advisee_progress, list_my_advisees
from aura_agent.tools.advisees import NOT_ADVISEE_MESSAGE, STAFF_ONLY_MESSAGE

from .conftest import BASE_URL, JWT, tool_call

PASSPORT_URL = "https://passport.test"
USERINFO_URL = f"{PASSPORT_URL}{USERINFO_PATH}"
USERS_URL = f"{BASE_URL}{USERS_PATH}"
ADVISOR_REF = "1577"
TEACHER_INFO = {
    "sub": 20002,
    "username": "teacher.t",
    "user_type": "staff",
    "user_type_id": ADVISOR_REF,
    "position_name": "อาจารย์",
    "display_name": "อาจารย์ทดสอบ ระบบ",
    "org_unit_1_name": "คณะวิทยาศาสตร์และเทคโนโลยี",
}


def user_row(code: str, passed: int, total: int, advisor: str | None = ADVISOR_REF) -> dict:
    """แถวจาก /v1/auth/users แบบเดียวกับของจริง รวมฟิลด์ส่วนตัวที่ต้องถูกทิ้ง"""
    return {
        "id": int(code[-4:]),
        "username": code,
        "name": f"นักศึกษา {code}",
        "fname": "นักศึกษา",
        "lname": f"สมมติ{code[-3:]}",
        "email": f"{code}@example.test",
        "telephone": "0800000000",
        "address": "บ้านเลขที่สมมติ",
        "roles": [],
        "program": "วิทยาการคอมพิวเตอร์",
        "student_status": "normal",
        "advisor_type_ref_id": advisor,
        "advisor_username": "teacher.t" if advisor == ADVISOR_REF else "other.t",
        "activity_summary": {"passed": passed, "total": total},
    }


ROWS = [
    user_row("406600101", 14, 14),
    user_row("406600102", 9, 14),
    user_row("406600103", 12, 14),
    user_row("406600104", 0, 0),
]


@pytest.fixture
async def passport_client(cache):
    passport = PassportClient(PASSPORT_URL, timeout_s=1.0, cache=cache, retry_delay_s=0)
    async with ActClient(
        BASE_URL, timeout_s=1.0, cache=cache, passport=passport, retry_delay_s=0
    ) as act_client:
        yield act_client


def mock_userinfo(respx_mock, **override):
    info = {**TEACHER_INFO, **override}
    return respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=info))


def mock_users(respx_mock, rows=ROWS):
    return respx_mock.get(USERS_URL).mock(return_value=httpx.Response(200, json={"data": rows}))


# ---- data ----


async def test_advisees_are_filtered_by_passport_user_type_id(passport_client, respx_mock):
    mock_userinfo(respx_mock)
    route = mock_users(respx_mock)

    advisees = await passport_client.get_advisees(JWT)

    request = route.calls.last.request
    assert request.url.params["advisor_type_ref_id"] == ADVISOR_REF
    assert request.url.params["type"] == "student"
    assert request.url.params["include_activity_summary"] == "1"
    assert "authorization" not in request.headers  # token ของ Passport ห้ามไปถึง Activity API
    assert [item.username for item in advisees] == [row["username"] for row in ROWS]


async def test_personal_fields_are_dropped(passport_client, respx_mock, cache):
    mock_userinfo(respx_mock)
    mock_users(respx_mock)

    advisee = (await passport_client.get_advisees(JWT))[0]

    dumped = advisee.model_dump()
    for field in ("email", "telephone", "address", "roles"):
        assert field not in dumped
    cached = [entry for entry in cache._cache.values() if isinstance(entry.value, list)]
    assert cached
    assert all("telephone" not in str(entry.value) for entry in cached)


async def test_rows_of_other_advisors_are_dropped(passport_client, respx_mock):
    """ถ้า API เมินตัวกรองแล้วคืนนักศึกษาทั้งมหาวิทยาลัย ต้องไม่หลุดถึงอาจารย์"""
    mock_userinfo(respx_mock)
    mock_users(respx_mock, [*ROWS, user_row("406600999", 1, 14, advisor="9999")])

    advisees = await passport_client.get_advisees(JWT)

    assert "406600999" not in {item.username for item in advisees}
    assert len(advisees) == len(ROWS)


async def test_students_have_no_advisees(passport_client, respx_mock):
    mock_userinfo(respx_mock, user_type="student", username="406600555", user_type_id="406600555")
    route = mock_users(respx_mock)

    assert await passport_client.get_advisees(JWT) == []
    assert route.call_count == 0


async def test_staff_without_reference_id_has_no_advisees(passport_client, respx_mock):
    mock_userinfo(respx_mock, user_type_id=None)
    route = mock_users(respx_mock)

    assert await passport_client.get_advisees(JWT) == []
    assert route.call_count == 0


async def test_advisees_are_cached(passport_client, respx_mock):
    mock_userinfo(respx_mock)
    route = mock_users(respx_mock)

    await passport_client.get_advisees(JWT)
    await passport_client.get_advisees(JWT)

    assert route.call_count == 1


async def test_advisee_summary_for_own_advisee(passport_client, respx_mock, load_fixture):
    mock_userinfo(respx_mock)
    mock_users(respx_mock)
    summary_route = respx_mock.get(f"{BASE_URL}{SUMMARY_USER_PATH}/406600102").mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    advisee, summary = await passport_client.get_advisee_summary(JWT, " 406600102 ")

    assert advisee.username == "406600102"
    assert summary.categories
    assert "authorization" not in summary_route.calls.last.request.headers


async def test_advisee_summary_refuses_other_students(passport_client, respx_mock):
    mock_userinfo(respx_mock)
    mock_users(respx_mock)
    summary_route = respx_mock.get(url__startswith=f"{BASE_URL}{SUMMARY_USER_PATH}/")

    with pytest.raises(NotYourAdvisee):
        await passport_client.get_advisee_summary(JWT, "406659012")

    assert summary_route.call_count == 0  # ไม่ดึงข้อมูลของคนที่ไม่อยู่ในรายชื่อเลย


def test_advisee_label_hides_the_advisor():
    assert ADVISOR_REF not in ADVISEES_LABEL


def test_passport_reads_user_type_id_but_not_citizen_id():
    user = PassportUser.model_validate(
        {**TEACHER_INFO, "user_type_id": 1577, "cid": "1234567890123"}
    )

    assert user.user_type_id == "1577"
    assert "cid" not in user.model_dump()


# ---- processing ----


def test_advisee_list_puts_incomplete_first():
    advisees = [Advisee.model_validate(row) for row in ROWS]

    text = format_advisees(advisees)
    lines = text.splitlines()

    assert lines[0] == (
        "[นักศึกษาในที่ปรึกษา] ทั้งหมด 4 คน | ครบตามเกณฑ์ 1 คน | ยังไม่ครบ 2 คน | ยังไม่มีกรอบกิจกรรม 1 คน"
    )
    assert lines[1].startswith("1. 406600102 ")  # ขาด 5 มากที่สุด
    assert "ผ่านเกณฑ์ 9/14 · ยังไม่ผ่าน 5" in lines[1]
    assert lines[2].startswith("2. 406600103 ")
    assert "ยังไม่มีกรอบกิจกรรม" in lines[3]
    assert "ครบแล้ว" in lines[4]
    assert "example.test" not in text


def test_advisee_list_only_incomplete():
    advisees = [Advisee.model_validate(row) for row in ROWS]

    text = format_advisees(advisees, only_incomplete=True)

    assert "406600101" not in text  # คนที่ครบแล้ว
    assert "406600102" in text


def test_empty_advisee_list():
    assert "ไม่พบรายชื่อนักศึกษาในที่ปรึกษา" in format_advisees([])


# ---- tool ----

TEACHER = StudentProfile.from_passport(PassportUser.model_validate(TEACHER_INFO))


class FakeAdvisorClient:
    """ActClient ปลอมสำหรับ tool ของอาจารย์"""

    def __init__(self, summary):
        self.summary = summary
        self.advisees = [Advisee.model_validate(row) for row in ROWS]
        self.calls: list[str] = []

    async def get_advisees(self, jwt):
        self.calls.append("get_advisees")
        return self.advisees

    async def get_advisee_summary(self, jwt, code):
        self.calls.append(f"get_advisee_summary:{code}")
        advisee = next((item for item in self.advisees if item.username == code), None)
        if advisee is None:
            raise NotYourAdvisee("x")
        return advisee, self.summary

    async def get_my_summary(self, jwt):
        from aura_agent.data import NotAStudent

        raise NotAStudent("staff", identity=PassportUser.model_validate(TEACHER_INFO))

    async def get_subject(self, jwt):
        return "passport:20002"

    async def get_schedules(self, jwt, **kwargs):
        return []


@pytest.fixture
def advisor_client(summary):
    from aura_agent.data import set_act_client

    fake = FakeAdvisorClient(summary)
    set_act_client(fake)
    yield fake
    set_act_client(None)


async def test_list_tool_for_teacher(advisor_client, tool_config):
    text = await list_my_advisees.ainvoke({"state": {"student": TEACHER}}, tool_config)

    assert text.startswith("[นักศึกษาในที่ปรึกษา] ทั้งหมด 4 คน")


async def test_advisor_tools_refuse_students(advisor_client, tool_config, student):
    listed = await list_my_advisees.ainvoke({"state": {"student": student}}, tool_config)
    detail = await get_advisee_progress.ainvoke(
        {"student_code": "406600102", "state": {"student": student}}, tool_config
    )

    assert listed == detail == STAFF_ONLY_MESSAGE
    assert advisor_client.calls == []


async def test_progress_tool_for_own_advisee(advisor_client, tool_config):
    text = await get_advisee_progress.ainvoke(
        {"student_code": "406600102", "state": {"student": TEACHER}}, tool_config
    )

    assert text.startswith("[ความคืบหน้าของนักศึกษาในที่ปรึกษา] 406600102 ")
    assert "[ความคืบหน้า]" in text


async def test_progress_tool_refuses_other_students(advisor_client, tool_config):
    text = await get_advisee_progress.ainvoke(
        {"student_code": "406659012", "state": {"student": TEACHER}}, tool_config
    )

    assert text == NOT_ADVISEE_MESSAGE.format(code="406659012")


@pytest.mark.parametrize("bad", ["นายสมมติ", "4066", "406600102; drop", ""])
async def test_progress_tool_rejects_non_codes(advisor_client, tool_config, bad):
    text = await get_advisee_progress.ainvoke(
        {"student_code": bad, "state": {"student": TEACHER}}, tool_config
    )

    assert "list_my_advisees" in text
    assert advisor_client.calls == []


# ---- prompt + graph ----


def test_teacher_gets_the_staff_prompt(frozen_today):
    from aura_agent import clock

    staff_prompt = render_system_prompt(clock.today(), TEACHER, "[ความคืบหน้า] บุคลากร")
    student_prompt = render_system_prompt(clock.today(), StudentProfile(id=1, name="ก"), None)

    assert "list_my_advisees" in staff_prompt
    assert "บุคลากร · อาจารย์" in staff_prompt
    assert "list_my_advisees" not in student_prompt


async def test_teacher_lists_advisees_through_graph(advisor_client, frozen_today, llm):
    fake = llm(tool_call("list_my_advisees"), AIMessage("มีนักศึกษาในที่ปรึกษา 4 คนครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("นักศึกษาในที่ปรึกษาผมมีใครบ้าง")]},
        run_config(user_id="passport:20002", thread_id="t", jwt=JWT),
    )

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("[นักศึกษาในที่ปรึกษา]")
    bound = set(fake.calls[0]["tools"])
    assert bound == {"search_activities", "list_my_advisees", "get_advisee_progress"}
