"""แปลง stream ของ graph เป็น SSE event ตาม docs/01-api-contract.md

| จาก graph | ส่งเป็น |
|---|---|
| chunk ของ node `agent` ที่มีข้อความ | `event: token` |
| chunk/ข้อความที่มีการเรียก tool | `event: status` (ครั้งเดียวต่อ tool) |
| ผลของ node อื่น เช่น `ToolMessage` | ไม่ส่ง (ผู้ใช้ไม่ต้องเห็นข้อมูลดิบ) |
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.messages import HumanMessage

from ..agent import message_text, run_config
from ..agent.errors import AgentError
from ..data import ActApiError, get_act_client
from ..tools import TOOL_STATUS
from .cleaner import AnswerCleaner

logger = logging.getLogger(__name__)

AGENT_NODE = "agent"
TOOLS_NODE = "tools"
STREAM_MODES = ["updates", "messages"]

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

DEFAULT_STATUS = "กำลังค้นหาข้อมูล..."
PARAGRAPH_BREAK = "\n\n"
INTERNAL_MESSAGE = "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งครับ"


# ---- event ----


def sse_event(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def status_event(text: str) -> dict[str, str]:
    return sse_event("status", {"text": text})


def token_event(text: str) -> dict[str, str]:
    return sse_event("token", {"text": text})


def done_event(thread_id: str, tools_used: list[str], latency_ms: int) -> dict[str, str]:
    return sse_event(
        "done",
        {"thread_id": thread_id, "tools_used": list(tools_used), "latency_ms": latency_ms},
    )


def error_event(code: str, text: str) -> dict[str, str]:
    return sse_event("error", {"code": code, "text": text})


# ---- ตัวกรอง thinking ----


class ThinkFilter:
    """ตัด `<think>...</think>` ออกจากข้อความที่ไหลมาเป็นชิ้นๆ

    qwen3.6 ปิด thinking ด้วย `reasoning=False` อยู่แล้ว ตัวนี้กันไว้เผื่อเปลี่ยนโมเดล
    และรองรับกรณี tag ถูกแบ่งคนละ chunk
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    def feed(self, text: str) -> str:
        if not text:
            return ""

        self._buffer += text
        parts: list[str] = []

        while self._buffer:
            if self._in_think:
                end = self._buffer.find(THINK_CLOSE)
                if end == -1:
                    self._buffer = _partial_tag_tail(self._buffer, THINK_CLOSE)
                    break
                self._buffer = self._buffer[end + len(THINK_CLOSE) :]
                self._in_think = False
                continue

            start = self._buffer.find(THINK_OPEN)
            if start == -1:
                safe, self._buffer = _split_partial_tag(self._buffer, THINK_OPEN)
                parts.append(safe)
                break

            parts.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(THINK_OPEN) :]
            self._in_think = True

        return "".join(parts)

    def flush(self) -> str:
        """ข้อความที่ค้างอยู่ตอนจบ stream (ถ้ายังอยู่ในโหมด think ให้ทิ้ง)"""
        text = "" if self._in_think else self._buffer
        self._buffer = ""
        return text


def _split_partial_tag(text: str, tag: str) -> tuple[str, str]:
    """กันท้ายข้อความที่อาจเป็นครึ่งแรกของ tag ไว้รอ chunk ถัดไป"""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return text[:-size], text[-size:]
    return text, ""


def _partial_tag_tail(text: str, tag: str) -> str:
    """อยู่ในโหมด think: ทิ้งเนื้อหา เก็บแค่ท้ายที่อาจเป็นครึ่งแรกของ tag ปิด"""
    _, tail = _split_partial_tag(text, tag)
    return tail


# ---- ตัวแปล stream ----


class StreamTranslator:
    """แปลง event ที่ได้จาก `graph.astream(stream_mode=["updates", "messages"])`"""

    def __init__(self) -> None:
        self.tools_used: list[str] = []
        self._announced: set[str] = set()
        self._think = ThinkFilter()
        self._cleaner = AnswerCleaner()
        # โมเดลบางครั้งพิมพ์ "รอสักครู่นะครับ" ก่อนเรียก tool แล้วคำตอบจริงต่อติดกันในบรรทัดเดียว
        # จึงขึ้นย่อหน้าใหม่ให้ข้อความแรกหลังเรียก tool (ข้อความที่ส่งไปแล้วดึงกลับไม่ได้)
        self._sent_text = False
        self._break_pending = False

    def handle(self, mode: str, payload: Any) -> Iterator[dict[str, str]]:
        if mode == "messages":
            yield from self._handle_message(payload)
        elif mode == "updates":
            yield from self._handle_update(payload)

    def flush(self) -> Iterator[dict[str, str]]:
        yield from self._emit(self._cleaner.feed(self._think.flush()))
        yield from self._emit(self._cleaner.flush())

    def _handle_message(self, payload: Any) -> Iterator[dict[str, str]]:
        chunk, metadata = payload
        if (metadata or {}).get("langgraph_node") != AGENT_NODE:
            return

        yield from self._emit(self._cleaner.feed(self._think.feed(message_text(chunk))))

        for call in getattr(chunk, "tool_call_chunks", None) or []:
            # ข้อความก่อนเรียก tool จบแล้ว ส่งส่วนที่ตัวกรองกันไว้ออกไปก่อนขึ้นย่อหน้าใหม่
            yield from self._emit(self._cleaner.flush())
            yield from self._announce(call.get("name"))

    def _emit(self, text: str) -> Iterator[dict[str, str]]:
        if not text:
            return
        if self._break_pending:
            text = text.lstrip()
            if not text:
                return
            text = PARAGRAPH_BREAK + text
            self._break_pending = False
        self._sent_text = True
        yield token_event(text)

    def _handle_update(self, payload: Any) -> Iterator[dict[str, str]]:
        if not isinstance(payload, dict):
            return
        self._learn_from_tools(payload.get(TOOLS_NODE))
        update = payload.get(AGENT_NODE)
        if not isinstance(update, dict):
            return

        for message in update.get("messages", []) or []:
            for call in getattr(message, "tool_calls", None) or []:
                yield from self._announce(call.get("name"))

    def _learn_from_tools(self, update: Any) -> None:
        """จำวันที่จากผลของ tool ให้ตัวกรองใช้แก้วันที่ที่โมเดลพิมพ์เดือนผิด (ผลของ tool ไม่ส่งถึงผู้ใช้)"""
        if not isinstance(update, dict):
            return
        for message in update.get("messages", []) or []:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                self._cleaner.learn_dates(content)

    def _announce(self, name: str | None) -> Iterator[dict[str, str]]:
        if self._sent_text:
            self._break_pending = True
        if not name or name in self._announced:
            return
        self._announced.add(name)
        self.tools_used.append(name)
        yield status_event(TOOL_STATUS.get(name, DEFAULT_STATUS))


# ---- ตัว stream ของ POST /v1/chat ----


ANONYMOUS_SUBJECT = "anonymous"


async def chat_events(
    graph: Any, *, thread_id: str, message: str, jwt: str | None
) -> AsyncIterator[dict[str, str]]:
    """ยืนยันตัวตน → เรียก graph → ส่ง status/token/done (หรือ error แทน done)"""
    started = time.perf_counter()
    translator = StreamTranslator()

    try:
        # ยืนยันตัวตนก่อน แล้วผูกประวัติแชทไว้กับผู้ใช้คนนี้ (ได้แม้ยังไม่มีกรอบกิจกรรม)
        # ไม่มี token = ผู้ใช้ทั่วไป ไม่ถาม Passport และไม่มีข้อมูลส่วนตัว (ประวัติแชทแยกด้วย thread_id)
        subject = await get_act_client().get_subject(jwt) if jwt else ANONYMOUS_SUBJECT
        config = run_config(user_id=subject, thread_id=thread_id, jwt=jwt)

        async for mode, payload in graph.astream(
            {"messages": [HumanMessage(message)], "tool_rounds": 0},
            config,
            stream_mode=STREAM_MODES,
        ):
            for event in translator.handle(mode, payload):
                yield event

        for event in translator.flush():
            yield event

        latency_ms = _elapsed_ms(started)
        logger.info("chat done tools=%s ms=%d", ",".join(translator.tools_used) or "-", latency_ms)
        yield done_event(thread_id, translator.tools_used, latency_ms)

    except (ActApiError, AgentError) as error:
        logger.warning("chat failed code=%s ms=%d", error.code, _elapsed_ms(started))
        yield error_event(error.code, error.message_th)
    except Exception:
        logger.exception("chat failed ms=%d", _elapsed_ms(started))
        yield error_event("INTERNAL", INTERNAL_MESSAGE)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
