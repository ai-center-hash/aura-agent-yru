"""Pipe Function สำหรับ Open WebUI / YRU Nexus (integrations/openwebui/aura_pipe.py)

จำลอง AURA API ด้วย respx · SSE ใช้ CRLF แบบเดียวกับ sse-starlette ของจริง
"""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

PIPE_PATH = Path(__file__).parents[2] / "integrations" / "openwebui" / "aura_pipe.py"
AURA = "http://aura.test:8100"
CHAT_URL = f"{AURA}/v1/chat"
OAUTH = {"access_token": "passport.access.token", "token_type": "Bearer"}
METADATA = {"chat_id": "c1f0a7e2-0000-4000-8000-000000000001"}


def load_pipe_module():
    spec = importlib.util.spec_from_file_location("aura_pipe", PIPE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["aura_pipe"] = module
    spec.loader.exec_module(module)
    return module


pipe_module = load_pipe_module()


def sse(*events: tuple[str, dict]) -> bytes:
    chunks = [
        f"event: {name}\r\ndata: {json.dumps(data, ensure_ascii=False)}\r\n\r\n"
        for name, data in events
    ]
    return "".join(chunks).encode()


def body(text: str = "ผมยังขาดหมวดไหน") -> dict:
    return {
        "messages": [{"role": "assistant", "content": "สวัสดีครับ"}, {"role": "user", "content": text}]
    }


@pytest.fixture
def pipe():
    instance = pipe_module.Pipe()
    instance.valves = instance.Valves(AURA_BASE_URL=AURA, AURA_SERVICE_KEY="k" * 32)
    return instance


@pytest.fixture
def emitted():
    events: list[dict] = []

    async def emitter(event):
        events.append(event)

    return events, emitter


async def collect(result) -> str:
    if isinstance(result, str):
        return result
    return "".join([part async for part in result])


def mock_aura(respx_mock, content: bytes, status: int = 200):
    return respx_mock.post(CHAT_URL).mock(
        return_value=httpx.Response(
            status, content=content, headers={"content-type": "text/event-stream"}
        )
    )


async def test_streams_answer_and_forwards_identity(pipe, respx_mock, emitted):
    events, emitter = emitted
    route = mock_aura(
        respx_mock,
        sse(
            ("status", {"text": "กำลังตรวจสอบความคืบหน้า..."}),
            ("token", {"text": "คุณยังขาด"}),
            ("token", {"text": "หมวดจิตอาสาครับ"}),
            ("done", {"thread_id": METADATA["chat_id"], "tools_used": ["get_my_progress"]}),
        ),
    )

    answer = await collect(
        await pipe.pipe(
            body(), __oauth_token__=OAUTH, __event_emitter__=emitter, __metadata__=METADATA
        )
    )

    assert answer == "คุณยังขาดหมวดจิตอาสาครับ"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer passport.access.token"
    assert request.headers["x-service-key"] == "k" * 32
    assert json.loads(request.content) == {
        "thread_id": METADATA["chat_id"],
        "message": "ผมยังขาดหมวดไหน",
    }
    assert events[0]["data"] == {
        "description": "กำลังตรวจสอบความคืบหน้า...",
        "done": False,
        "hidden": False,
    }
    assert events[-1]["data"]["done"] is True


async def test_only_the_latest_user_message_is_sent(pipe, respx_mock):
    route = mock_aura(respx_mock, sse(("token", {"text": "ok"}), ("done", {})))
    messages = {
        "messages": [
            {"role": "user", "content": "คำถามเก่า"},
            {"role": "assistant", "content": "คำตอบเก่า"},
            {"role": "user", "content": [{"type": "text", "text": "คำถามใหม่"}]},
        ]
    }

    await collect(await pipe.pipe(messages, __oauth_token__=OAUTH, __metadata__=METADATA))

    assert json.loads(route.calls.last.request.content)["message"] == "คำถามใหม่"


async def test_password_login_users_are_asked_to_use_passport(pipe, respx_mock):
    route = respx_mock.post(CHAT_URL)

    answer = await collect(await pipe.pipe(body(), __oauth_token__=None, __metadata__=METADATA))

    assert answer == pipe_module.LOGIN_REQUIRED
    assert route.call_count == 0


@pytest.mark.parametrize("task", ["title_generation", "tags_generation", "follow_up_generation"])
async def test_background_tasks_never_reach_aura(pipe, respx_mock, task):
    route = respx_mock.post(CHAT_URL)

    answer = await pipe.pipe(body(), __oauth_token__=OAUTH, __metadata__=METADATA, __task__=task)

    assert route.call_count == 0
    assert isinstance(json.loads(answer), dict)


async def test_aura_error_event_is_shown(pipe, respx_mock):
    mock_aura(
        respx_mock,
        sse(("error", {"code": "TOKEN_EXPIRED", "text": "เซสชันหมดอายุแล้วครับ"})),
    )

    answer = await collect(await pipe.pipe(body(), __oauth_token__=OAUTH, __metadata__=METADATA))

    assert answer == "เซสชันหมดอายุแล้วครับ"


async def test_wrong_service_key(pipe, respx_mock):
    mock_aura(respx_mock, b'{"detail":"x"}', status=401)

    answer = await collect(await pipe.pipe(body(), __oauth_token__=OAUTH, __metadata__=METADATA))

    assert answer == pipe_module.SERVICE_REJECTED


async def test_aura_unreachable(pipe, respx_mock):
    respx_mock.post(CHAT_URL).mock(side_effect=httpx.ConnectError("down"))

    answer = await collect(await pipe.pipe(body(), __oauth_token__=OAUTH, __metadata__=METADATA))

    assert answer == pipe_module.UNREACHABLE


async def test_missing_service_key(respx_mock):
    pipe = pipe_module.Pipe()

    answer = await pipe.pipe(body(), __oauth_token__=OAUTH, __metadata__=METADATA)

    assert answer == pipe_module.NOT_CONFIGURED


async def test_long_question_is_refused_before_calling(pipe, respx_mock):
    route = respx_mock.post(CHAT_URL)

    answer = await pipe.pipe(body("ก" * 1001), __oauth_token__=OAUTH, __metadata__=METADATA)

    assert answer == pipe_module.TOO_LONG
    assert route.call_count == 0


async def test_temporary_chat_uses_a_per_user_thread(pipe, respx_mock):
    route = mock_aura(respx_mock, sse(("done", {})))

    await collect(
        await pipe.pipe(
            body(),
            __oauth_token__=OAUTH,
            __metadata__={"chat_id": "local:abc"},
            __user__={"id": "user-1"},
        )
    )

    assert json.loads(route.calls.last.request.content)["thread_id"] == "nexus-user-1"


def test_pipe_exposes_one_model(pipe):
    assert pipe.pipes() == [{"id": "aura", "name": "AURA กิจกรรมนักศึกษา"}]
