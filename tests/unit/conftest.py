"""fixture ที่ใช้ร่วมกันใน unit test"""

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from aura_agent.data import ActClient, MemoryCache
from aura_agent.data.schemas import Registration, Schedule, StudentSummary
from aura_agent.processing import StudentProfile

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"

BASE_URL = "https://act.test/act/api"
JWT = "header.payload.testsignature"  # token ปลอมสำหรับ test ห้ามใช้ token จริง
OTHER_JWT = "header.payload.anotherstudent"


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    """อ่าน JSON จาก tests/fixtures/"""

    def _load(name: str) -> Any:
        return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return _load


class FakeClock:
    """นาฬิกาปลอม ใช้ทดสอบ TTL ของ cache โดยไม่ต้องรอเวลาจริง"""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(clock: FakeClock) -> MemoryCache:
    return MemoryCache(timer=clock)


@pytest.fixture
async def client(cache: MemoryCache):
    """ActClient ที่ไม่หน่วงเวลาตอน retry เพื่อให้ test เร็ว"""
    async with ActClient(BASE_URL, timeout_s=1.0, cache=cache, retry_delay_s=0) as act_client:
        yield act_client


# ---- ข้อมูลที่ parse จาก fixture แล้ว (ใช้ใน test ของชั้น processing) ----

TODAY = date(2026, 10, 20)  # วันอ้างอิงของ fixture ดู tests/fixtures/README.md


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def summary(load_fixture) -> StudentSummary:
    return StudentSummary.model_validate(load_fixture("summary_me.json")["data"])


@pytest.fixture
def schedules(load_fixture) -> list[Schedule]:
    return [Schedule.model_validate(row) for row in load_fixture("schedules.json")["data"]]


@pytest.fixture
def registrations(load_fixture) -> list[Registration]:
    return [Registration.model_validate(row) for row in load_fixture("registrations.json")["data"]]


@pytest.fixture
def student(summary: StudentSummary) -> StudentProfile:
    return StudentProfile.from_user(summary.user)


# ---- ของปลอมสำหรับ test ชั้น tools/agent ----


class FakeActClient:
    """ActClient ปลอม คืนข้อมูลจาก fixture และจำว่าถูกเรียกด้วยอะไรบ้าง"""

    def __init__(self, summary, schedules, registrations):
        self.summary = summary
        self.schedules = schedules
        self.registrations = registrations
        self.calls: list[tuple[str, dict]] = []

    async def get_my_summary(self, jwt: str):
        self.calls.append(("get_my_summary", {"jwt": jwt}))
        return self.summary

    async def get_subject(self, jwt: str) -> str:
        # เหมือนโหมด activity_me: ตัวตนมาจาก summary (test ที่แทน get_my_summary ด้วย error จึงยังใช้ได้)
        return str((await self.get_my_summary(jwt)).user.id)

    async def get_schedules(self, jwt: str, **kwargs):
        self.calls.append(("get_schedules", {"jwt": jwt, **kwargs}))
        return self.schedules

    async def get_registrations(self, jwt: str, user_id: int):
        self.calls.append(("get_registrations", {"jwt": jwt, "user_id": user_id}))
        return self.registrations

    async def ping(self) -> bool:
        return True

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict:
        return next(params for called, params in reversed(self.calls) if called == name)


@pytest.fixture
def act_client(summary, schedules, registrations):
    """ติดตั้ง client ปลอมให้ tool ทุกตัวใช้ แล้วถอดออกเมื่อจบ test"""
    from aura_agent.data import set_act_client

    fake = FakeActClient(summary, schedules, registrations)
    set_act_client(fake)
    yield fake
    set_act_client(None)


@pytest.fixture
def frozen_today(monkeypatch):
    """ตรึง "วันนี้" ให้ตรงกับวันอ้างอิงของ fixture"""
    from aura_agent import clock

    monkeypatch.setattr(clock, "today", lambda: TODAY)
    return TODAY


@pytest.fixture
def tool_config() -> dict:
    return {"configurable": {"jwt": JWT}}


# ---- LLM ปลอม ----


class FakeLLM:
    """LLM ปลอมแบบ duck-typed: คืนคำตอบตามคิว และจำว่าแต่ละครั้ง bind tools มาด้วยไหม"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def bind_tools(self, tools):
        return BoundFakeLLM(self, tools)

    async def ainvoke(self, messages, config=None, **_):
        return self._record(messages, bound=False)

    def _record(self, messages, *, bound: bool):
        self.calls.append({"bound": bound, "messages": messages})
        if self.responses:
            return self.responses.pop(0)
        return AIMessage("ตอบจากข้อมูลที่มีครับ")


class BoundFakeLLM:
    def __init__(self, parent: FakeLLM, tools):
        self.parent = parent
        self.tools = tools

    async def ainvoke(self, messages, config=None, **_):
        return self.parent._record(messages, bound=True)


class FakeChat(BaseChatModel):
    """LLM ปลอมที่ stream ข้อความออกมาเป็นชิ้นๆ จริง และ stream message ที่เรียก tool ได้

    (`GenericFakeChatModel` ของ langchain stream message ที่ไม่มี content ไม่ได้)
    """

    queue: list[AIMessage] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def _next(self) -> AIMessage:
        if self.queue:
            return self.queue.pop(0)
        return AIMessage("ตอบจากข้อมูลที่มีครับ")

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._next()
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"], ensure_ascii=False),
                            "id": call["id"],
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                        for index, call in enumerate(message.tool_calls)
                    ],
                )
            )
            return
        for part in re.split(r"(\s)", str(message.content)):
            if part:
                yield ChatGenerationChunk(message=AIMessageChunk(content=part))


def tool_call(name: str, call_id: str = "1", **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.fixture
def llm():
    """ติดตั้ง FakeLLM ให้ node agent ใช้"""
    from aura_agent.agent import set_llm

    def _install(*responses: AIMessage) -> FakeLLM:
        fake = FakeLLM(*responses)
        set_llm(fake)
        return fake

    yield _install
    set_llm(None)


@pytest.fixture
def chat_model():
    """ติดตั้ง FakeChat (stream ได้) ให้ node agent ใช้"""
    from aura_agent.agent import set_llm

    def _install(*responses: AIMessage) -> FakeChat:
        model = FakeChat(queue=list(responses))
        set_llm(model)
        return model

    yield _install
    set_llm(None)


# ---- settings สำหรับ test ของ API ----

SERVICE_KEY = "test-service-key-0123456789"
OLLAMA_URL = "http://ollama.test:11434"


@pytest.fixture
def settings_env(monkeypatch):
    """ตั้งค่า .env ชั่วคราวให้ test ของ API ใช้ค่าที่รู้แน่นอน"""
    from aura_agent.config import get_settings

    monkeypatch.setenv("SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setenv("OLLAMA_BASE_URL", OLLAMA_URL)
    monkeypatch.setenv("LLM_MODEL", "qwen3.6:35b-a3b")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def api_headers() -> dict[str, str]:
    return {"X-Service-Key": SERVICE_KEY, "Authorization": f"Bearer {JWT}"}
