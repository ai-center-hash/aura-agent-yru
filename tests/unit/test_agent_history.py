"""test ของการเลือกประวัติแชทช่วงท้ายที่ส่งให้โมเดล (agent/history.py)"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from aura_agent.agent.history import recent_messages

from .conftest import tool_call


def turn(index: int, size: int = 10) -> list:
    """คำถาม 1 ข้อที่เรียก tool 1 ครั้ง: human → ai(tool call) → tool → ai(คำตอบ)"""
    return [
        HumanMessage(f"คำถาม {index}"),
        tool_call("search_activities", call_id=str(index)),
        ToolMessage("ก" * size, tool_call_id=str(index)),
        AIMessage(f"คำตอบ {index}"),
    ]


def contents(messages: list) -> list[str]:
    return [m.content for m in messages if isinstance(m, HumanMessage)]


def test_short_history_is_sent_whole():
    messages = [*turn(1), *turn(2), HumanMessage("คำถาม 3")]

    assert recent_messages(messages) == messages


def test_keeps_only_the_latest_turns():
    messages = [message for index in range(1, 11) for message in turn(index)]

    kept = recent_messages(messages, max_turns=3)

    assert contents(kept) == ["คำถาม 8", "คำถาม 9", "คำถาม 10"]


def test_cuts_at_a_question_so_tool_results_keep_their_call():
    messages = [*turn(1, size=500), *turn(2, size=500), *turn(3, size=500)]

    kept = recent_messages(messages, max_chars=1200)

    assert isinstance(kept[0], HumanMessage)
    assert contents(kept) == ["คำถาม 2", "คำถาม 3"]
    call_ids = {call["id"] for m in kept if isinstance(m, AIMessage) for call in m.tool_calls}
    assert {m.tool_call_id for m in kept if isinstance(m, ToolMessage)} <= call_ids


def test_current_question_is_always_sent_even_when_over_budget():
    messages = [*turn(1), HumanMessage("คำถามปัจจุบัน"), tool_call("get_my_progress", "9")]
    messages.append(ToolMessage("ข" * 50_000, tool_call_id="9"))

    kept = recent_messages(messages, max_chars=100)

    assert contents(kept) == ["คำถามปัจจุบัน"]
    assert kept[-1].content == "ข" * 50_000


def test_without_any_question_returns_everything():
    messages = [AIMessage("สวัสดีครับ")]

    assert recent_messages(messages) == messages
