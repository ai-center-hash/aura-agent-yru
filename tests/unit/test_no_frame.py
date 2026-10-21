"""นักศึกษาที่ระบบกิจกรรมยังไม่มีกรอบกิจกรรมให้ (`no_frame: true`)

เจอจริงกับบัญชีทดสอบเมื่อ 2026-10-21 · เดิมโค้ดจะพังเป็น UpstreamSchemaError
ตอนนี้ต้องคุยต่อได้: บอกว่ายังไม่มีกรอบกิจกรรม แต่ยังค้นหากิจกรรมได้
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import build_graph, run_config, state_serializer
from aura_agent.data import NoActivityFrame
from aura_agent.data.schemas import PassportUser
from aura_agent.processing import StudentProfile
from aura_agent.tools import get_my_progress, get_my_registrations, recommend_activities
from aura_agent.tools.recommend import NO_FRAME_MESSAGE as RECOMMEND_NO_FRAME
from aura_agent.tools.registrations import NO_FRAME_MESSAGE as REGISTRATIONS_NO_FRAME

from .conftest import JWT, tool_call

API_MESSAGE = "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้"
IDENTITY = PassportUser(
    sub="10001",
    username="406500001",
    user_type="student",
    display_name="นักศึกษาทดสอบ ไม่มีกรอบ",
    org_unit_1_name="คณะวิทยาศาสตร์และเทคโนโลยี",
)


@pytest.fixture
def no_frame_client(act_client):
    """ActClient ปลอมที่ทำเหมือน API จริงตอนนักศึกษาไม่มีกรอบกิจกรรม"""

    async def no_frame(jwt: str):
        act_client.calls.append(("get_my_summary", {"jwt": jwt}))
        raise NoActivityFrame(API_MESSAGE, identity=IDENTITY)

    async def subject(jwt: str) -> str:
        return f"passport:{IDENTITY.sub}"

    act_client.get_my_summary = no_frame
    act_client.get_subject = subject
    return act_client


@pytest.fixture
def no_frame_student() -> StudentProfile:
    return StudentProfile.from_passport(IDENTITY)


# ---- tool ----


async def test_progress_tool_explains_missing_frame(no_frame_client, tool_config):
    text = await get_my_progress.ainvoke({}, tool_config)

    assert text.startswith("[ความคืบหน้า] ยังไม่มีกรอบกิจกรรม")
    assert API_MESSAGE in text


async def test_recommend_tool_explains_missing_frame(
    no_frame_client, tool_config, no_frame_student, frozen_today
):
    text = await recommend_activities.ainvoke({"state": {"student": no_frame_student}}, tool_config)

    assert text == RECOMMEND_NO_FRAME.format(reason=API_MESSAGE)
    assert "get_schedules" not in no_frame_client.names()


async def test_registrations_tool_needs_user_id(no_frame_client, tool_config, no_frame_student):
    text = await get_my_registrations.ainvoke({"state": {"student": no_frame_student}}, tool_config)

    assert text == REGISTRATIONS_NO_FRAME
    assert "get_registrations" not in no_frame_client.names()  # ไม่เดา user_id เอง


# ---- graph ----


async def test_load_student_builds_profile_from_passport(no_frame_client, frozen_today, llm):
    llm(AIMessage("ตอนนี้ยังไม่มีกรอบกิจกรรมของคุณครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("ผมขาดหมวดไหน")]},
        run_config(user_id="passport:10001", thread_id="t", jwt=JWT),
    )

    student = state["student"]
    assert isinstance(student, StudentProfile)
    assert student.id is None
    assert student.student_id == "406500001"
    assert student.name == "นักศึกษาทดสอบ ไม่มีกรอบ"
    assert state["progress_text"].startswith("[ความคืบหน้า] ยังไม่มีกรอบกิจกรรม")


async def test_search_still_works_without_frame(no_frame_client, frozen_today, llm):
    llm(tool_call("search_activities", phase="open"), AIMessage("มีกิจกรรมเปิดรับอยู่ครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("มีกิจกรรมอะไรเปิดรับสมัคร")]},
        run_config(user_id="passport:10001", thread_id="t", jwt=JWT),
    )

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("[กิจกรรมที่สมัครได้]")


async def test_system_prompt_tells_the_model_there_is_no_frame(no_frame_client, frozen_today, llm):
    fake = llm(AIMessage("รับทราบครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    await graph.ainvoke(
        {"messages": [HumanMessage("สวัสดี")]},
        run_config(user_id="passport:10001", thread_id="t", jwt=JWT),
    )

    system_prompt = fake.calls[0]["messages"][0].content
    assert "ยังไม่มีกรอบกิจกรรม" in system_prompt
    assert "นักศึกษาทดสอบ ไม่มีกรอบ" in system_prompt
