"""test ของตัวแปล stream → SSE (ThinkFilter, StreamTranslator และรูปแบบ event)"""

import json

from langchain_core.messages import AIMessage, AIMessageChunk

from aura_agent.api.sse import (
    StreamTranslator,
    ThinkFilter,
    done_event,
    error_event,
    status_event,
    token_event,
)

AGENT_META = {"langgraph_node": "agent"}
TOOLS_META = {"langgraph_node": "tools"}


def data_of(event: dict[str, str]) -> dict:
    return json.loads(event["data"])


def texts(events: list[dict[str, str]]) -> str:
    return "".join(data_of(event)["text"] for event in events if event["event"] == "token")


# ---- รูปแบบ event ----


def test_event_shapes():
    assert status_event("กำลังค้นหา...") == {
        "event": "status",
        "data": '{"text": "กำลังค้นหา..."}',
    }
    assert data_of(token_event("คุณยัง")) == {"text": "คุณยัง"}
    assert data_of(error_event("TOKEN_EXPIRED", "เข้าสู่ระบบใหม่")) == {
        "code": "TOKEN_EXPIRED",
        "text": "เข้าสู่ระบบใหม่",
    }


def test_done_event_fields():
    event = done_event("t1", ["get_my_progress"], 4120)

    assert event["event"] == "done"
    assert data_of(event) == {
        "thread_id": "t1",
        "tools_used": ["get_my_progress"],
        "latency_ms": 4120,
    }


def test_thai_text_is_not_escaped():
    """frontend อ่านง่ายและ payload เล็กกว่า"""
    assert "\\u" not in token_event("ภาษาไทย")["data"]


# ---- ThinkFilter ----


def test_think_filter_passes_normal_text():
    think = ThinkFilter()

    assert think.feed("คุณยังขาด 2 หมวดครับ") == "คุณยังขาด 2 หมวดครับ"
    assert think.flush() == ""


def test_think_filter_removes_block_in_one_chunk():
    think = ThinkFilter()

    assert think.feed("<think>คิดอยู่</think>คำตอบ") == "คำตอบ"


def test_think_filter_removes_block_split_across_chunks():
    think = ThinkFilter()
    out = [
        think.feed("ก่อน<thi"),
        think.feed("nk>ซ่อน"),
        think.feed("ไว้</think"),
        think.feed(">หลัง"),
    ]

    assert "".join(out) == "ก่อนหลัง"
    assert think.flush() == ""


def test_think_filter_drops_unterminated_block():
    think = ThinkFilter()

    assert think.feed("ตอบ<think>คิดค้างไว้") == "ตอบ"
    assert think.flush() == ""


def test_think_filter_holds_back_possible_tag_prefix():
    think = ThinkFilter()

    assert think.feed("จบแล้ว<") == "จบแล้ว"
    assert think.flush() == "<"  # ไม่ใช่ tag จริง ต้องส่งคืนตอนจบ


def test_think_filter_ignores_empty_input():
    think = ThinkFilter()

    assert think.feed("") == ""


# ---- StreamTranslator ----


def test_translator_turns_chunks_into_tokens():
    translator = StreamTranslator()

    events = [
        *translator.handle("messages", (AIMessageChunk(content="คุณยัง"), AGENT_META)),
        *translator.handle("messages", (AIMessageChunk(content="ขาด 2 หมวด"), AGENT_META)),
    ]

    assert texts(events) == "คุณยังขาด 2 หมวด"
    assert translator.tools_used == []


def test_translator_skips_other_nodes():
    translator = StreamTranslator()

    events = list(translator.handle("messages", (AIMessageChunk(content="[ข้อมูลดิบ]"), TOOLS_META)))

    assert events == []


def test_translator_announces_tool_from_chunk():
    translator = StreamTranslator()
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": "search_activities",
                "args": "{}",
                "id": "1",
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )

    events = list(translator.handle("messages", (chunk, AGENT_META)))

    assert data_of(events[0]) == {"text": "กำลังค้นหากิจกรรม..."}
    assert translator.tools_used == ["search_activities"]


def test_translator_announces_tool_from_updates():
    translator = StreamTranslator()
    message = AIMessage("", tool_calls=[{"name": "get_my_progress", "args": {}, "id": "1"}])

    events = list(translator.handle("updates", {"agent": {"messages": [message]}}))

    assert data_of(events[0]) == {"text": "กำลังตรวจสอบความคืบหน้า..."}
    assert translator.tools_used == ["get_my_progress"]


def test_translator_announces_each_tool_once():
    translator = StreamTranslator()
    message = AIMessage("", tool_calls=[{"name": "get_my_progress", "args": {}, "id": "1"}])

    first = list(translator.handle("updates", {"agent": {"messages": [message]}}))
    again = list(translator.handle("updates", {"agent": {"messages": [message]}}))

    assert len(first) == 1
    assert again == []
    assert translator.tools_used == ["get_my_progress"]


def test_translator_uses_default_status_for_unknown_tool():
    translator = StreamTranslator()
    message = AIMessage("", tool_calls=[{"name": "something_new", "args": {}, "id": "1"}])

    events = list(translator.handle("updates", {"agent": {"messages": [message]}}))

    assert data_of(events[0]) == {"text": "กำลังค้นหาข้อมูล..."}


def test_translator_ignores_updates_from_other_nodes():
    translator = StreamTranslator()

    assert list(translator.handle("updates", {"tools": {"messages": ["ข้อมูลดิบ"]}})) == []
    assert list(translator.handle("updates", {"load_student": {"tool_rounds": 0}})) == []
    assert list(translator.handle("updates", "ไม่ใช่ dict")) == []
    assert list(translator.handle("values", {"messages": []})) == []


def test_translator_strips_think_tags_while_streaming():
    translator = StreamTranslator()

    events = [
        *translator.handle("messages", (AIMessageChunk(content="<think>คิด"), AGENT_META)),
        *translator.handle("messages", (AIMessageChunk(content="ต่อ</think>คำ"), AGENT_META)),
        *translator.handle("messages", (AIMessageChunk(content="ตอบครับ"), AGENT_META)),
    ]

    assert texts(events) == "คำตอบครับ"


def test_translator_flushes_pending_text():
    translator = StreamTranslator()
    list(translator.handle("messages", (AIMessageChunk(content="จบ<"), AGENT_META)))

    assert texts(list(translator.flush())) == "<"
