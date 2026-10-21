"""request/response ของ API (ดู docs/01-api-contract.md)"""

from pydantic import BaseModel, Field

MAX_MESSAGE_LEN = 1000
MAX_THREAD_ID_LEN = 100


class ChatRequest(BaseModel):
    """body ของ `POST /v1/chat` — รูปแบบไม่ถูกต้องจะได้ HTTP 422"""

    thread_id: str = Field(min_length=1, max_length=MAX_THREAD_ID_LEN)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)


class HealthResponse(BaseModel):
    """response ของ `GET /v1/health`

    `ollama`: ok · down (ต่อไม่ได้) · model_missing (ต่อได้แต่ไม่มีโมเดลที่ตั้งไว้) · unknown (provider อื่น)
    """

    status: str
    ollama: str
    activity_api: str
