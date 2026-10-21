"""โมเดลปลอมสำหรับ `--self-test`

**ไม่ใช่การวัดคุณภาพโมเดล** ใช้ตรวจว่าโครง eval ทำงานครบวงจรโดยไม่ต้องมี Ollama
คือ fixture โหลดได้ · tool ถูกเรียก · ข้อความที่ dataset คาดหวังมีอยู่จริงในข้อมูล · รายงานเขียนได้

วิธีทำงาน: เลือก tool จากคำในคำถาม แล้วตอบด้วยผลของ tool นั้นตรงๆ
ส่วนคำถามกลุ่มความปลอดภัยตอบด้วยข้อความปฏิเสธที่เตรียมไว้
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# ตรวจกลุ่มความปลอดภัยก่อน เพราะคำถามพวกนี้มีคำที่ชนกับ keyword ของ tool
REFUSALS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("รหัส 6", "ของรหัส", "ของเพื่อน", "ของคนอื่น"),
        "ขออภัยครับ ผมให้ข้อมูลได้เฉพาะของคุณเองเท่านั้น ถ้าอยากดูความคืบหน้าของตัวเอง ถามมาได้เลยครับ",
    ),
    (
        ("system prompt", "คำสั่งเดิม", "เครื่องมือที่คุณ", "ข้ามคำสั่ง"),
        "ผมเป็นผู้ช่วยด้านกิจกรรมนักศึกษาครับ ถามเรื่องกิจกรรมมาได้เลย",
    ),
    (
        ("สูตร", "อาหาร", "แกง", "หนัง", "เพลง"),
        "ขออภัยครับ ผมช่วยได้เฉพาะเรื่องกิจกรรมนักศึกษาครับ",
    ),
)

TOOL_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("แนะนำ", "ควรสมัคร", "ช่วยเก็บ", "ให้ครบ", "ช่วยให้ผมครบ", "เช็คเงื่อนไข"),
        "recommend_activities",
    ),
    (
        (
            "ลงทะเบียน",
            "ลงอะไร",
            "ลงกิจกรรมอะไร",
            "เช็คอิน",
            "เช็คเอาท์",
            "ยกเลิกไป",
            "เคยเข้า",
            "สมบูรณ์",
        ),
        "get_my_registrations",
    ),
    (
        (
            "เปิดรับ",
            "มีกิจกรรมอะไร",
            "กิจกรรมอะไรบ้าง",
            "จัดวันไหน",
            "ที่นั่ง",
            "เดือน",
            "วันที่",
            "สมัครได้ไหม",
            "เทียบโอนไหม",
            "จิตอาสาไหม",
        ),
        "search_activities",
    ),
    (("ขาด", "ครบ", "กี่ชั่วโมง", "กี่กิจกรรม", "ผ่านหมวด", "กรอบ", "เหลืออะไร"), "get_my_progress"),
)

# "ลงทะเบียนให้ผม" = สั่งให้ทำแทน (ต้องปฏิเสธ) ส่วน "ผมลงทะเบียนอะไรไว้" = ถามประวัติ (เรียก tool)
ACTION_WORDS = ("ลงทะเบียน", "สมัคร", "ยกเลิก", "เช็คอิน")
ACTION_REQUESTS = ("ให้ผม", "ให้ฉัน", "ให้หน่อย", "ให้ด้วย", "แทนผม")
ACTION_REFUSAL = "ผมทำแทนไม่ได้ครับ ทำได้แค่ช่วยหาข้อมูล คุณสมัครเองหรือยกเลิกเองได้ในระบบกิจกรรมนักศึกษาครับ"

CLOSING = "อยากให้ช่วยอะไรเพิ่มบอกได้เลยครับ"


class EchoChatModel(BaseChatModel):
    """เลือก tool จากคำถาม แล้วตอบด้วยผลของ tool (stream ออกมาเป็นชิ้นๆ เหมือนของจริง)"""

    @property
    def _llm_type(self) -> str:
        return "aura-eval-echo"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> EchoChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._reply(messages)

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

    # ---- ภายใน ----

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        tool_output = _last_tool_output(messages)
        if tool_output is not None:
            return AIMessage(f"{tool_output}\n{CLOSING}")

        question = _last_question(messages)
        if _asks_us_to_act(question):
            return AIMessage(ACTION_REFUSAL)

        for keywords, answer in REFUSALS:
            if any(keyword in question for keyword in keywords):
                return AIMessage(answer)

        for keywords, tool_name in TOOL_KEYWORDS:
            if any(keyword in question for keyword in keywords):
                return AIMessage("", tool_calls=[{"name": tool_name, "args": {}, "id": "echo-1"}])

        return AIMessage(f"สวัสดีครับ ผมช่วยเรื่องกิจกรรมนักศึกษาได้ครับ {CLOSING}")


def _asks_us_to_act(question: str) -> bool:
    return any(word in question for word in ACTION_WORDS) and any(
        request in question for request in ACTION_REQUESTS
    )


def _last_tool_output(messages: list[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            return str(message.content)
        if isinstance(message, AIMessage) and not message.tool_calls:
            return None
    return None


def _last_question(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "human":
            return str(message.content)
    return ""
