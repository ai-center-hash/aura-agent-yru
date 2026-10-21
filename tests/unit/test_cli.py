"""test ของ CLI เฉพาะส่วนที่ทดสอบได้โดยไม่ต้องมี Ollama หรือ JWT จริง"""

from langchain_core.messages import AIMessage, AIMessageChunk

from aura_agent.cli import chunk_text, main


async def test_main_without_jwt_exits_with_code_2(monkeypatch, capsys):
    monkeypatch.delenv("AURA_DEV_JWT", raising=False)

    assert await main() == 2
    assert "AURA_DEV_JWT" in capsys.readouterr().out


async def test_main_reports_api_error(monkeypatch, capsys):
    from aura_agent.data import TokenExpired, set_act_client

    class BrokenClient:
        async def get_subject(self, jwt: str) -> str:
            raise TokenExpired("/oidc/userinfo: HTTP 401")

        async def get_my_summary(self, jwt: str):
            raise TokenExpired("/v1/report/summary/me: HTTP 401")

        async def aclose(self) -> None:
            return None

    monkeypatch.setenv("AURA_DEV_JWT", "header.payload.test")
    set_act_client(BrokenClient())
    try:
        code = await main()
    finally:
        set_act_client(None)

    assert code == 1
    assert "TOKEN_EXPIRED" in capsys.readouterr().out


def test_chunk_text_reads_plain_content():
    assert chunk_text(AIMessageChunk(content="สวัสดี")) == "สวัสดี"


def test_chunk_text_reads_content_blocks():
    chunk = AIMessageChunk(
        content=[{"type": "text", "text": "ส่วนแรก"}, {"type": "text", "text": "ส่วนสอง"}]
    )

    assert chunk_text(chunk) == "ส่วนแรกส่วนสอง"


def test_chunk_text_skips_tool_call_messages():
    message = AIMessage("", tool_calls=[{"name": "get_my_progress", "args": {}, "id": "1"}])

    assert chunk_text(message) == ""


def test_chunk_text_handles_unknown_object():
    assert chunk_text(object()) == ""


class FakeGraph:
    """graph ปลอมที่ปล่อย event ตามที่กำหนด (หรือโยน error)"""

    def __init__(self, *events, error: Exception | None = None):
        self.events = events
        self.error = error
        self.calls: list[tuple] = []

    def astream(self, state, config, stream_mode=None):
        self.calls.append((state, config, stream_mode))

        async def generate():
            for event in self.events:
                yield event
            if self.error is not None:
                raise self.error

        return generate()


async def test_ask_prints_tool_status_and_streams_answer(capsys):
    from aura_agent.cli import ask

    graph = FakeGraph(
        ("updates", {"agent": {"messages": [tool_call_message()]}}),
        ("messages", (AIMessageChunk(content="คุณยัง"), {"langgraph_node": "agent"})),
        ("messages", (AIMessageChunk(content="ขาด 2 หมวด"), {"langgraph_node": "agent"})),
        ("messages", (AIMessageChunk(content="ไม่ควรแสดง"), {"langgraph_node": "tools"})),
    )

    await ask(graph, "ผมขาดหมวดไหน", user_id=119231, thread_id="t1", jwt="j")
    output = capsys.readouterr().out

    assert "[กำลังตรวจสอบความคืบหน้า...]" in output
    assert "คุณยังขาด 2 หมวด" in output
    assert "ไม่ควรแสดง" not in output
    assert "ms)" in output

    state, config, stream_mode = graph.calls[0]
    assert config["configurable"]["thread_id"] == "119231:t1"
    assert config["configurable"]["jwt"] == "j"
    assert stream_mode == ["updates", "messages"]


async def test_ask_reports_api_error_in_thai(capsys):
    from aura_agent.cli import ask
    from aura_agent.data import UpstreamUnavailable

    graph = FakeGraph(error=UpstreamUnavailable("timeout"))

    await ask(graph, "มีกิจกรรมอะไร", user_id=1, thread_id="t", jwt="j")
    output = capsys.readouterr().out

    assert "[UPSTREAM_UNAVAILABLE]" in output
    assert "ระบบกิจกรรมไม่พร้อมใช้งาน" in output


async def test_ask_reports_unexpected_error(capsys):
    from aura_agent.cli import ask

    graph = FakeGraph(error=RuntimeError("boom"))

    await ask(graph, "สวัสดี", user_id=1, thread_id="t", jwt="j")

    assert "[ERROR] RuntimeError: boom" in capsys.readouterr().out


def tool_call_message() -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "get_my_progress", "args": {}, "id": "1"}])
