"""
title: AURA กิจกรรมนักศึกษา
author: AI Center มรย.
description: แชทบอทกิจกรรมนักศึกษา มรย. — ส่งคำถามและ token YRU Passport ของผู้ใช้ไปที่ AURA API
version: 0.1.0
"""

# Pipe Function สำหรับ Open WebUI / YRU Nexus · ติดตั้งตาม docs/05-openwebui-nexus.md
#
# หน้าที่ของไฟล์นี้มีแค่ "ส่งต่อ": คำถามล่าสุด + chat_id + access token ของ YRU Passport
# ที่ผู้ใช้ login ไว้ใน Nexus → POST {AURA}/v1/chat แล้วแปลง SSE กลับเป็นข้อความในหน้าแชท
# ตัวตนและสิทธิ์ (นักศึกษา/อาจารย์/เจ้าหน้าที่) AURA ตัดสินเองจาก token · ไฟล์นี้ไม่ log token
# ใช้ได้เฉพาะผู้ใช้ที่ login ด้วย YRU Passport (บัญชีรหัสผ่านของ Nexus ไม่มี token ให้ส่ง)

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

MAX_MESSAGE_CHARS = 1000  # ตรงกับ docs/01-api-contract.md

LOGIN_REQUIRED = (
    "AURA ใช้ได้เมื่อเข้าสู่ระบบด้วย **YRU Passport** เท่านั้นครับ กรุณาออกจากระบบ แล้วเข้าใหม่ด้วยปุ่ม YRU Passport"
)
TOO_LONG = f"คำถามยาวเกินไปครับ (ไม่เกิน {MAX_MESSAGE_CHARS} ตัวอักษร) ลองถามให้สั้นลงนะครับ"
EMPTY_QUESTION = "พิมพ์คำถามเรื่องกิจกรรมนักศึกษาได้เลยครับ"
NOT_CONFIGURED = "ผู้ดูแลระบบยังไม่ได้ตั้งค่า AURA (AURA_SERVICE_KEY) ครับ"
SERVICE_REJECTED = "ระบบ AURA ปฏิเสธการเชื่อมต่อจาก Nexus ครับ (service key ไม่ถูกต้อง) รบกวนแจ้งผู้ดูแลระบบ"
UNREACHABLE = "ตอนนี้ติดต่อระบบ AURA ไม่ได้ครับ ลองใหม่อีกครั้งในอีกสักครู่"
INTERRUPTED = "\n\n(การตอบถูกตัดกลางทาง ลองถามใหม่อีกครั้งครับ)"

Emitter = Callable[[dict[str, Any]], Awaitable[None]] | None


class Pipe:
    class Valves(BaseModel):
        AURA_BASE_URL: str = Field(
            default="http://10.20.41.54:8100", description="URL ของ AURA API (ไม่ต้องมี / ท้าย)"
        )
        AURA_SERVICE_KEY: str = Field(
            default="", description="ค่า SERVICE_KEY ใน /opt/aura-agent/.env บนเครื่อง AURA"
        )
        MODEL_NAME: str = Field(default="AURA กิจกรรมนักศึกษา", description="ชื่อโมเดลที่ผู้ใช้เห็น")
        TIMEOUT_S: float = Field(default=120.0, description="รอคำตอบนานสุดกี่วินาที")

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": "aura", "name": self.valves.MODEL_NAME}]

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any] | None = None,
        __oauth_token__: dict[str, Any] | None = None,
        __event_emitter__: Emitter = None,
        __metadata__: dict[str, Any] | None = None,
        __task__: str | None = None,
    ) -> str | AsyncGenerator[str, None]:
        question = _last_user_text(body.get("messages") or [])

        # งานเบื้องหลังของ Open WebUI (ตั้งชื่อแชท แท็ก คำถามต่อ) ไม่ส่งไป AURA
        # เพื่อไม่ให้ไปปนในประวัติแชทของผู้ใช้และไม่เสียเวลาโมเดล
        if __task__:
            return _task_reply(str(__task__), question)

        token = (__oauth_token__ or {}).get("access_token")
        if not token:
            return LOGIN_REQUIRED
        if not self.valves.AURA_SERVICE_KEY:
            return NOT_CONFIGURED
        if not question:
            return EMPTY_QUESTION
        if len(question) > MAX_MESSAGE_CHARS:
            return TOO_LONG

        thread_id = _thread_id(__metadata__, __user__)
        return self._stream(question, thread_id, str(token), __event_emitter__)

    async def _stream(
        self, question: str, thread_id: str, token: str, emit: Emitter
    ) -> AsyncGenerator[str, None]:
        url = f"{self.valves.AURA_BASE_URL.rstrip('/')}/v1/chat"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Service-Key": self.valves.AURA_SERVICE_KEY,
            "Accept": "text/event-stream",
        }
        payload = {"thread_id": thread_id, "message": question}
        answered = False

        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code == 401:
                        yield SERVICE_REJECTED
                        return
                    if response.status_code >= 400:
                        yield UNREACHABLE
                        return

                    async for event, data in _sse_events(response):
                        if event == "status":
                            await _status(emit, data.get("text", ""), done=False)
                        elif event == "token":
                            answered = True
                            yield data.get("text", "")
                        elif event == "error":
                            await _status(emit, "", done=True)
                            yield ("\n\n" if answered else "") + data.get("text", UNREACHABLE)
                            return
                        elif event == "done":
                            await _status(emit, "", done=True)
                            return
        except httpx.HTTPError:
            await _status(emit, "", done=True)
            yield INTERRUPTED if answered else UNREACHABLE


async def _sse_events(response: httpx.Response) -> AsyncGenerator[tuple[str, dict], None]:
    """อ่าน SSE ของ AURA (sse-starlette คั่นด้วย CRLF) ทีละ event"""
    event, data_lines = "message", []
    async for line in response.aiter_lines():
        line = line.rstrip("\r")
        if not line:
            if data_lines:
                yield event, _json("\n".join(data_lines))
            event, data_lines = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        yield event, _json("\n".join(data_lines))


def _json(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return value if isinstance(value, dict) else {"text": str(value)}


async def _status(emit: Emitter, text: str, *, done: bool) -> None:
    if emit is None:
        return
    await emit({"type": "status", "data": {"description": text, "done": done, "hidden": done}})


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """ข้อความล่าสุดของผู้ใช้ (content เป็น string หรือ list ของ part ก็ได้)"""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return str(content or "").strip()
    return ""


def _thread_id(metadata: dict[str, Any] | None, user: dict[str, Any] | None) -> str:
    """ห้องแชทของ Nexus = ห้องแชทของ AURA (AURA ผูกกับตัวตนจาก token อีกชั้น)"""
    chat_id = (metadata or {}).get("chat_id")
    if chat_id and not str(chat_id).startswith("local:"):
        return str(chat_id)
    return f"nexus-{(user or {}).get('id', 'anonymous')}"


def _task_reply(task: str, question: str) -> str:
    if task == "title_generation":
        title = question[:40] or "กิจกรรมนักศึกษา"
        return json.dumps({"title": title}, ensure_ascii=False)
    if task == "tags_generation":
        return json.dumps({"tags": ["กิจกรรมนักศึกษา"]}, ensure_ascii=False)
    if task == "follow_up_generation":
        return json.dumps({"follow_ups": []})
    return ""
