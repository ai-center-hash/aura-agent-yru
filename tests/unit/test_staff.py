"""บุคลากร (อาจารย์ เจ้าหน้าที่ แอดมิน) ที่ login ผ่าน YRU Passport

ขั้นที่ 1 (2026-10-22): คุยได้และค้นหารอบกิจกรรมได้ทุกรอบที่ยังรับสมัคร
แต่ไม่มีความคืบหน้า ประวัติ หรือคำแนะนำของตัวเอง และดูข้อมูลนักศึกษาคนอื่นไม่ได้
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import build_graph, run_config, state_serializer
from aura_agent.agent.prompts import STAFF_TYPE
from aura_agent.data import NotAStudent
from aura_agent.data.schemas import PassportUser
from aura_agent.processing import (
    StudentProfile,
    filter_eligible,
    filter_open,
    format_not_student,
    format_schedules,
)
from aura_agent.processing.formatter import MAX_ITEMS, OPEN_SCHEDULES_TITLE, RESTRICTED_TAG
from aura_agent.tools import (
    get_my_progress,
    get_my_registrations,
    recommend_activities,
    search_activities,
)

from .conftest import JWT, tool_call

STAFF = PassportUser(
    sub="20002",
    username="somchai.j",
    user_type="staff",
    display_name="อาจารย์ทดสอบ ระบบ",
    org_unit_1_name="คณะวิทยาศาสตร์เทคโนโลยีและการเกษตร",
)


@pytest.fixture
def staff_client(act_client):
    """ActClient ปลอมที่ทำเหมือนโหมด passport ตอนเจ้าของ token เป็นบุคลากร"""

    async def not_a_student(jwt: str):
        act_client.calls.append(("get_my_summary", {"jwt": jwt}))
        raise NotAStudent("user_type=staff", identity=STAFF)

    async def subject(jwt: str) -> str:
        return f"passport:{STAFF.sub}"

    act_client.get_my_summary = not_a_student
    act_client.get_subject = subject
    return act_client


@pytest.fixture
def staff() -> StudentProfile:
    return StudentProfile.from_passport(STAFF)


# ---- processing ----


def test_staff_profile_has_no_student_code(staff):
    assert staff.is_student is False
    assert staff.student_id is None  # username ของบุคลากรไม่ใช่รหัสนักศึกษา
    assert staff.id is None
    assert staff.faculty == "คณะวิทยาศาสตร์เทคโนโลยีและการเกษตร"


def test_open_filter_keeps_restricted_rounds(schedules, frozen_today):
    student = StudentProfile(id=1, name="นักศึกษา", faculty="คณะอื่น", student_id="406599999")

    open_ids = {item.schedule.id for item in filter_open(schedules, frozen_today)}
    eligible_ids = {item.schedule.id for item in filter_eligible(schedules, student, frozen_today)}

    assert eligible_ids < open_ids  # บุคลากรเห็นรอบที่จำกัดกลุ่มด้วย
    for schedule in schedules:
        if schedule.id in open_ids:
            assert not schedule.is_full


def test_staff_schedule_list_tags_restricted_rounds(schedules, frozen_today):
    items = filter_open(schedules, frozen_today)

    text = format_schedules(items, for_staff=True)

    assert text.startswith(f"[{OPEN_SCHEDULES_TITLE}]")
    restricted = [item for item in items if item.schedule.is_restricted]
    assert restricted
    assert text.count(RESTRICTED_TAG) == sum(
        1 for item in items[:MAX_ITEMS] if item.schedule.is_restricted
    )
    assert "ไม่แน่ใจเรื่องสิทธิ์สมัคร" not in text


def test_not_student_text_names_the_unit():
    text = format_not_student("สำนักวิทยบริการ")

    assert text.startswith("[ความคืบหน้า] ผู้ใช้คนนี้เป็นบุคลากร")
    assert "สำนักวิทยบริการ" in text
    assert "ที่ไม่ได้อยู่ในที่ปรึกษา" in text


# ---- tool ----


async def test_progress_tool_says_staff_has_no_progress(staff_client, tool_config):
    text = await get_my_progress.ainvoke({}, tool_config)

    assert "บุคลากร" in text
    assert "ความคืบหน้ากิจกรรม" in text


async def test_registrations_tool_never_queries_for_staff(staff_client, tool_config, staff):
    text = await get_my_registrations.ainvoke({"state": {"student": staff}}, tool_config)

    assert "บุคลากร" in text
    assert "get_registrations" not in staff_client.names()


async def test_recommend_tool_never_queries_for_staff(staff_client, tool_config, staff):
    text = await recommend_activities.ainvoke({"state": {"student": staff}}, tool_config)

    assert "บุคลากร" in text
    assert staff_client.names() == []


async def test_search_tool_shows_all_open_rounds_to_staff(
    staff_client, tool_config, staff, frozen_today
):
    text = await search_activities.ainvoke({"state": {"student": staff}}, tool_config)

    assert text.startswith(f"[{OPEN_SCHEDULES_TITLE}]")
    assert "get_schedules" in staff_client.names()


# ---- graph ----


async def test_load_student_builds_staff_profile(staff_client, frozen_today, llm):
    fake = llm(AIMessage("สวัสดีครับอาจารย์"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("สวัสดี")]},
        run_config(user_id="passport:20002", thread_id="t", jwt=JWT),
    )

    student = state["student"]
    assert isinstance(student, StudentProfile)
    assert student.is_student is False
    assert state["progress_text"].startswith("[ความคืบหน้า] ผู้ใช้คนนี้เป็นบุคลากร")
    system_prompt = fake.calls[0]["messages"][0].content
    assert STAFF_TYPE in system_prompt
    assert "อาจารย์ทดสอบ ระบบ" in system_prompt


async def test_staff_profile_survives_checkpoint_round_trip(staff_client, frozen_today, llm):
    llm(AIMessage("สวัสดีครับ"), AIMessage("ได้ครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))
    config = run_config(user_id="passport:20002", thread_id="t", jwt=JWT)

    await graph.ainvoke({"messages": [HumanMessage("สวัสดี")]}, config)
    state = await graph.ainvoke({"messages": [HumanMessage("ขอบคุณ")]}, config)

    assert state["student"].is_student is False


async def test_staff_search_through_graph(staff_client, frozen_today, llm):
    llm(tool_call("search_activities", phase="open"), AIMessage("มีกิจกรรมเปิดรับอยู่ครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("มีกิจกรรมอะไรเปิดรับสมัคร")]},
        run_config(user_id="passport:20002", thread_id="t", jwt=JWT),
    )

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith(f"[{OPEN_SCHEDULES_TITLE}]")
