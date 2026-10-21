"""Exception ของชั้น agent

`code` และ `message_th` ตรงกับตาราง error ใน docs/01-api-contract.md เหมือนกับ `data/errors.py`
"""

import httpx


class AgentError(Exception):
    """error พื้นฐานของชั้น agent"""

    code = "INTERNAL"
    message_th = "ขออภัยครับ ระบบมีปัญหาชั่วคราว ลองใหม่อีกครั้งนะครับ"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail or self.code)


class LLMUnavailable(AgentError):
    """เรียกโมเดลไม่ได้ (Ollama ล่ม, tunnel ปิด, โมเดลยังไม่ถูกโหลด)"""

    code = "LLM_UNAVAILABLE"
    message_th = "ผู้ช่วยไม่พร้อมใช้งานชั่วคราวครับ ลองใหม่อีกครั้งในอีกสักครู่"


try:  # ollama เป็น dependency ของ langchain-ollama
    from ollama import RequestError, ResponseError

    _OLLAMA_ERRORS: tuple[type[BaseException], ...] = (RequestError, ResponseError)
except ImportError:  # pragma: no cover - เมื่อใช้ provider อื่น
    _OLLAMA_ERRORS = ()

# error ที่แปลว่า "เรียกโมเดลไม่ได้" ไม่ใช่ "โมเดลตอบแปลก"
LLM_ERRORS: tuple[type[BaseException], ...] = (httpx.HTTPError, OSError, *_OLLAMA_ERRORS)
