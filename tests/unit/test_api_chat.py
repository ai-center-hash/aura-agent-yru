"""test ของ `POST /v1/chat` และ `DELETE /v1/chat/{thread_id}` (ไม่ต่อ Ollama และไม่ต่อ Activity API)"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import build_graph, run_config, state_serializer
from aura_agent.api.main import create_app
from aura_agent.data import TokenExpired, UpstreamUnavailable

from .conftest import JWT, SERVICE_KEY, tool_call

CHAT_URL = "/v1/chat"


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """แปลง body ของ SSE เป็น [(event, data), ...]"""
    events: list[tuple[str, dict]] = []
    event: str | None = None
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:") and event:
            events.append((event, json.loads(line[len("data:") :].strip())))
    return events


def events_of(body: str, name: str) -> list[dict]:
    return [data for event, data in parse_sse(body) if event == name]


def answer_of(body: str) -> str:
    return "".join(data["text"] for data in events_of(body, "token"))


@pytest.fixture
async def api(act_client, frozen_today, settings_env, chat_model):
    """สร้าง app + client ที่ใช้ graph จริงแต่ LLM และ Activity API เป็นของปลอม"""
    clients: list[AsyncClient] = []

    class Api:
        def __init__(self) -> None:
            self.graph = None

        def build(self, *responses: AIMessage) -> AsyncClient:
            chat_model(*responses)
            self.graph = build_graph(InMemorySaver(serde=state_serializer()))
            app = create_app(graph=self.graph)
            client = AsyncClient(transport=ASGITransport(app=app), base_url="http://aura.test")
            clients.append(client)
            return client

    harness = Api()
    yield harness
    for client in clients:
        await client.aclose()


# ---- auth ----


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": f"Bearer {JWT}"},
        {"X-Service-Key": "wrong-service-key", "Authorization": f"Bearer {JWT}"},
        {"X-Service-Key": SERVICE_KEY, "Authorization": JWT},
        {"X-Service-Key": SERVICE_KEY, "Authorization": "Bearer "},
    ],
)
async def test_chat_rejects_bad_service_key_or_malformed_token(api, headers):
    client = api.build(AIMessage("สวัสดีครับ"))

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=headers
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"thread_id": "t1"},
        {"message": "สวัสดี"},
        {"thread_id": "t1", "message": ""},
        {"thread_id": "", "message": "สวัสดี"},
        {"thread_id": "t1", "message": "ก" * 1001},
    ],
)
async def test_chat_rejects_bad_body(api, api_headers, payload):
    client = api.build(AIMessage("สวัสดีครับ"))

    response = await client.post(CHAT_URL, json=payload, headers=api_headers)

    assert response.status_code == 422


# ---- ทางเดินปกติ ----


async def test_chat_streams_tokens_and_done(api, api_headers):
    client = api.build(AIMessage("สวัสดีครับ ผมช่วยเรื่องกิจกรรมได้ครับ"))

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=api_headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    names = [event for event, _ in parse_sse(response.text)]
    assert names[-1] == "done"
    assert names.count("token") > 1  # ไหลมาทีละชิ้น ไม่ใช่ก้อนเดียว
    assert answer_of(response.text) == "สวัสดีครับ ผมช่วยเรื่องกิจกรรมได้ครับ"

    done = events_of(response.text, "done")[0]
    assert done["thread_id"] == "t1"
    assert done["tools_used"] == []
    assert done["latency_ms"] >= 0


async def test_chat_sends_status_before_tokens(api, api_headers):
    client = api.build(tool_call("get_my_progress"), AIMessage("คุณยังขาด 2 หมวดครับ"))

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "ผมขาดหมวดไหน"}, headers=api_headers
    )

    names = [event for event, _ in parse_sse(response.text)]
    assert names[0] == "status"
    assert names.index("status") < names.index("token")
    assert events_of(response.text, "status")[0]["text"] == "กำลังตรวจสอบความคืบหน้า..."
    assert answer_of(response.text) == "คุณยังขาด 2 หมวดครับ"
    assert events_of(response.text, "done")[0]["tools_used"] == ["get_my_progress"]


async def test_chat_does_not_leak_tool_output(api, api_headers):
    """ผู้ใช้ต้องไม่เห็นข้อความดิบจาก tool ผ่าน event: token"""
    client = api.build(tool_call("search_activities", phase="open"), AIMessage("มี 5 กิจกรรมครับ"))

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "มีกิจกรรมอะไร"}, headers=api_headers
    )

    assert "[กิจกรรมที่สมัครได้]" not in answer_of(response.text)
    assert answer_of(response.text) == "มี 5 กิจกรรมครับ"


async def test_chat_keeps_history_per_thread(api, api_headers):
    client = api.build(AIMessage("คำตอบแรก"), AIMessage("คำตอบสอง"))

    await client.post(CHAT_URL, json={"thread_id": "t1", "message": "ถามแรก"}, headers=api_headers)
    await client.post(CHAT_URL, json={"thread_id": "t1", "message": "ถามสอง"}, headers=api_headers)

    state = await api.graph.aget_state(run_config(user_id=119231, thread_id="t1", jwt=JWT))
    assert [message.content for message in state.values["messages"]] == [
        "ถามแรก",
        "คำตอบแรก",
        "ถามสอง",
        "คำตอบสอง",
    ]


async def test_other_student_cannot_read_the_same_thread_id(api, api_headers, act_client, summary):
    """thread_id เดียวกันแต่คนละ JWT ต้องเป็นคนละห้อง (key คือ user_id:thread_id)"""
    client = api.build(AIMessage("ของคนแรก"), AIMessage("ของคนที่สอง"))

    await client.post(
        CHAT_URL, json={"thread_id": "shared", "message": "ความลับ"}, headers=api_headers
    )

    other_user = summary.user.model_copy(update={"id": 999999})
    act_client.summary = summary.model_copy(update={"user": other_user})
    await client.post(
        CHAT_URL, json={"thread_id": "shared", "message": "ขอดูของคนอื่น"}, headers=api_headers
    )

    first = await api.graph.aget_state(run_config(user_id=119231, thread_id="shared", jwt=JWT))
    second = await api.graph.aget_state(run_config(user_id=999999, thread_id="shared", jwt=JWT))

    assert [m.content for m in first.values["messages"]] == ["ความลับ", "ของคนแรก"]
    assert [m.content for m in second.values["messages"]] == ["ขอดูของคนอื่น", "ของคนที่สอง"]


# ---- error ----


async def test_expired_token_becomes_error_event(api, api_headers, act_client):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    async def expired(jwt: str):
        raise TokenExpired("/v1/report/summary/me: HTTP 401")

    act_client.get_my_summary = expired

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=api_headers
    )

    assert response.status_code == 200  # ตาม contract: error ส่งใน stream
    error = events_of(response.text, "error")[0]
    assert error["code"] == "TOKEN_EXPIRED"
    assert "เข้าสู่ระบบใหม่" in error["text"]
    assert events_of(response.text, "done") == []


async def test_upstream_error_becomes_error_event(api, api_headers, act_client):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    async def unavailable(jwt: str):
        raise UpstreamUnavailable("timeout")

    act_client.get_my_summary = unavailable

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=api_headers
    )

    assert events_of(response.text, "error")[0]["code"] == "UPSTREAM_UNAVAILABLE"


async def test_llm_down_becomes_error_event(api, api_headers):
    import httpx

    from aura_agent.agent import set_llm

    class BrokenLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, config=None, **_):
            raise httpx.ConnectError("connection refused")

    client = api.build(AIMessage("ไม่ได้ใช้"))
    set_llm(BrokenLLM())

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=api_headers
    )

    error = events_of(response.text, "error")[0]
    assert error["code"] == "LLM_UNAVAILABLE"
    assert "ผู้ช่วยไม่พร้อมใช้งาน" in error["text"]


async def test_unexpected_error_becomes_internal(api, api_headers, act_client):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    async def boom(jwt: str):
        raise RuntimeError("อะไรก็ไม่รู้")

    act_client.get_my_summary = boom

    response = await client.post(
        CHAT_URL, json={"thread_id": "t1", "message": "สวัสดี"}, headers=api_headers
    )

    assert events_of(response.text, "error")[0]["code"] == "INTERNAL"


# ---- ลบประวัติแชท ----


async def test_delete_thread_removes_only_own_history(api, api_headers):
    client = api.build(AIMessage("คำตอบแรก"), AIMessage("คำตอบสอง"))
    await client.post(CHAT_URL, json={"thread_id": "t1", "message": "ถาม"}, headers=api_headers)
    await client.post(CHAT_URL, json={"thread_id": "t2", "message": "ถาม"}, headers=api_headers)

    response = await client.delete(f"{CHAT_URL}/t1", headers=api_headers)

    assert response.status_code == 204
    gone = await api.graph.aget_state(run_config(user_id=119231, thread_id="t1", jwt=JWT))
    kept = await api.graph.aget_state(run_config(user_id=119231, thread_id="t2", jwt=JWT))
    assert gone.values == {}
    assert kept.values["messages"]


async def test_delete_thread_requires_headers(api):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    assert (await client.delete(f"{CHAT_URL}/t1")).status_code == 401


async def test_delete_thread_with_expired_token(api, api_headers, act_client):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    async def expired(jwt: str):
        raise TokenExpired("HTTP 401")

    act_client.get_my_summary = expired

    response = await client.delete(f"{CHAT_URL}/t1", headers=api_headers)

    assert response.status_code == 401


async def test_delete_thread_when_activity_api_down(api, api_headers, act_client):
    client = api.build(AIMessage("ไม่ได้ใช้"))

    async def unavailable(jwt: str):
        raise UpstreamUnavailable("timeout")

    act_client.get_my_summary = unavailable

    response = await client.delete(f"{CHAT_URL}/t1", headers=api_headers)

    assert response.status_code == 503


# ---- ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ (ไม่ส่ง Authorization) · 2026-10-22 ----


ANON_THREAD = "c1f0a7e2-5b3d-4f6a-9e8c-2d7b1a0f4e6c"


async def test_chat_without_token_is_allowed_as_anonymous(api, act_client):
    client = api.build(tool_call("search_activities", phase="open"), AIMessage("มีกิจกรรมเปิดรับครับ"))

    response = await client.post(
        CHAT_URL,
        json={"thread_id": ANON_THREAD, "message": "มีกิจกรรมอะไรเปิดรับสมัคร"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert response.status_code == 200
    assert answer_of(response.text) == "มีกิจกรรมเปิดรับครับ"
    assert events_of(response.text, "done")
    # ไม่ถามตัวตนและไม่ดึงข้อมูลส่วนตัว ดึงแค่รอบกิจกรรม (ข้อมูลสาธารณะ) โดยไม่มี token
    assert "get_my_summary" not in act_client.names()
    assert act_client.last("get_schedules")["jwt"] == ""


async def test_anonymous_thread_is_kept_apart_from_logged_in_users(api):
    client = api.build(AIMessage("สวัสดีครับ"))

    await client.post(
        CHAT_URL,
        json={"thread_id": ANON_THREAD, "message": "สวัสดี"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    state = await api.graph.aget_state(
        run_config(user_id="anonymous", thread_id=ANON_THREAD, jwt=None)
    )
    assert state.values["student"].is_anonymous is True
    other = await api.graph.aget_state(run_config(user_id="119231", thread_id=ANON_THREAD, jwt=JWT))
    assert not other.values


@pytest.mark.parametrize("thread_id", ["1", "shared", "nexus-42"])
async def test_anonymous_thread_id_must_be_uuid(api, thread_id):
    """ผู้ใช้ทั่วไปทุกคนใช้ subject เดียวกัน thread_id ที่เดาได้จะทำให้เห็นแชทของคนอื่น"""
    client = api.build(AIMessage("สวัสดีครับ"))

    response = await client.post(
        CHAT_URL,
        json={"thread_id": thread_id, "message": "สวัสดี"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert response.status_code == 422
    assert not (
        await api.graph.aget_state(run_config(user_id="anonymous", thread_id=thread_id, jwt=None))
    ).values


async def test_logged_in_thread_id_does_not_need_uuid(api, api_headers):
    """ผู้ใช้ที่เข้าสู่ระบบแล้ว ห้องแชทผูกกับตัวตนอยู่แล้ว (เช่น Open WebUI ส่ง nexus-{id})"""
    client = api.build(AIMessage("สวัสดีครับ"))

    response = await client.post(
        CHAT_URL, json={"thread_id": "nexus-42", "message": "สวัสดี"}, headers=api_headers
    )

    assert response.status_code == 200
