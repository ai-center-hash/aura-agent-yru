"""อ่านข้อความจาก message chunk ที่ LangGraph ส่งออกมา

langchain คืน `content` เป็น string หรือเป็น list ของ content block แล้วแต่โมเดล
ชั้น api (SSE) และ cli ใช้ฟังก์ชันนี้ร่วมกัน
"""

from typing import Any

from langchain_core.messages import AIMessage


def message_text(chunk: Any) -> str:
    """ข้อความที่ผู้ใช้ควรเห็น (ข้อความของ message ที่เรียก tool ถือว่าไม่มีเนื้อหา)"""
    if isinstance(chunk, AIMessage) and getattr(chunk, "tool_calls", None):
        return ""

    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""
