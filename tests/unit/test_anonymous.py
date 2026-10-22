"""ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ (ไม่ส่ง Authorization) · ตัดสิน 2026-10-22

ทุกบทบาทใช้ tool ชุดเดียวกัน ผู้ใช้ทั่วไปค้นหารอบกิจกรรมได้ แต่ไม่มีข้อมูลส่วนตัวของใคร
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import build_graph, run_config, state_serializer
from aura_agent.agent.prompts import ANONYMOUS_TYPE
from aura_agent.processing import StudentProfile
from aura_agent.processing.formatter import OPEN_SCHEDULES_TITLE
from aura_agent.tools import (
    get_advisee_progress,
    get_my_progress,
    get_my_registrations,
    list_my_advisees,
    recommend_activities,
    search_activities,
)
from aura_agent.tools.context import LOGIN_REQUIRED_MESSAGE

ANONYMOUS = StudentProfile.anonymous()
NO_TOKEN = {"configurable": {}}


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (get_my_progress, {}),
        (get_my_registrations, {}),
        (recommend_activities, {}),
        (list_my_advisees, {}),
        (get_advisee_progress, {"student_code": "406600102"}),
    ],
    ids=lambda value: getattr(value, "name", ""),
)
async def test_personal_tools_ask_anonymous_users_to_log_in(act_client, tool, args):
    text = await tool.ainvoke({**args, "state": {"student": ANONYMOUS}}, NO_TOKEN)

    assert text == LOGIN_REQUIRED_MESSAGE
    assert act_client.names() == []  # ไม่เรียก API ใดเลย


async def test_anonymous_users_can_search_all_open_rounds(act_client, frozen_today):
    text = await search_activities.ainvoke({"state": {"student": ANONYMOUS}}, NO_TOKEN)

    assert text.startswith(f"[{OPEN_SCHEDULES_TITLE}]")
    assert act_client.last("get_schedules")["jwt"] == ""


async def test_graph_builds_anonymous_profile_without_calling_apis(act_client, frozen_today, llm):
    fake = llm(AIMessage("สวัสดีครับ"))
    graph = build_graph(InMemorySaver(serde=state_serializer()))

    state = await graph.ainvoke(
        {"messages": [HumanMessage("สวัสดี")]},
        run_config(user_id="anonymous", thread_id="t", jwt=None),
    )

    assert state["student"].is_anonymous is True
    assert state["progress_text"].startswith("[ความคืบหน้า] ผู้ใช้ยังไม่ได้เข้าสู่ระบบ")
    assert act_client.names() == []
    assert ANONYMOUS_TYPE in fake.calls[0]["messages"][0].content
