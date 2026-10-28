"""เลือกประวัติแชทช่วงท้ายที่จะส่งให้โมเดล

state ยังเก็บประวัติครบ (ข้อความเก่าถูกลบด้วย `scripts/prune_threads.py`) แต่ส่งให้โมเดลแค่ช่วงท้าย
เพราะถ้าเกิน `LLM_NUM_CTX` Ollama จะทิ้งข้อความเก่าเองโดยไม่บอก (vLLM จะ error)
และ prompt ที่ยาวทำให้ทุกคนรอคิวนานขึ้น เพราะเซิร์ฟเวอร์ตอบได้ทีละคำขอ

- ตัดที่ต้นคำถามของผู้ใช้ (`HumanMessage`) เสมอ ผลของ tool จะได้ไม่หลุดจาก tool call ที่คู่กัน
- คำถามปัจจุบัน รวมผลของ tool ในรอบนี้ ส่งครบเสมอแม้จะยาวเกินงบ
"""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage

MAX_HISTORY_TURNS = 8  # คำถามล่าสุดที่ส่งให้โมเดล (รวมคำถามปัจจุบัน)
# system prompt ~5.2k ตัวอักษร + schema ของ tool + คำตอบ ต้องพอดีกับ num_ctx 16384 token
# ภาษาไทยประมาณ 1.5–2 ตัวอักษรต่อ token จึงเหลือให้ประวัติราว 12k ตัวอักษร
MAX_HISTORY_CHARS = 12_000


def recent_messages(
    messages: Sequence[BaseMessage],
    *,
    max_turns: int = MAX_HISTORY_TURNS,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[BaseMessage]:
    """ข้อความตั้งแต่ต้นคำถามที่เก่าที่สุดที่ยังอยู่ในงบ `max_turns` และ `max_chars`"""
    starts = [index for index, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if not starts:
        return list(messages)

    starts = starts[-max_turns:]
    keep_from = starts[-1]
    for start in reversed(starts[:-1]):
        if _size(messages[start:]) > max_chars:
            break
        keep_from = start
    return list(messages[keep_from:])


def _size(messages: Sequence[BaseMessage]) -> int:
    return sum(len(_text(message)) for message in messages)


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))
