"""`POST /v1/chat` และ `DELETE /v1/chat/{thread_id}`"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sse_starlette.sse import EventSourceResponse

from ...agent import thread_key
from ...data import ActApiError, TokenExpired, get_act_client
from ..deps import Graph, Jwt, OptionalJwt, ServiceKey
from ..schemas import ChatRequest
from ..sse import chat_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])

NO_CHECKPOINTER = "ระบบยังไม่พร้อมใช้งาน"
ANONYMOUS_THREAD_NOT_UUID = "ผู้ใช้ที่ไม่ได้เข้าสู่ระบบต้องส่ง thread_id เป็น UUID"


@router.post("/chat")
async def chat(
    payload: ChatRequest, graph: Graph, jwt: OptionalJwt, _service_key: ServiceKey
) -> EventSourceResponse:
    """ถามคำถาม แล้ว stream คำตอบกลับเป็น SSE (HTTP ยัง 200 แม้จะมี `event: error`)

    ไม่ส่ง Authorization = ผู้ใช้ทั่วไป ค้นหากิจกรรมได้ แต่ไม่มีข้อมูลส่วนตัวของใคร
    ผู้ใช้ทั่วไปทุกคนใช้ subject เดียวกัน ห้องแชทจึงแยกกันด้วย thread_id อย่างเดียว
    ต้องเป็น UUID เพื่อไม่ให้ thread_id ที่เดาได้ (เช่น "1") ทำให้คนละคนเห็นแชทของกัน
    """
    if jwt is None and not _is_uuid(payload.thread_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, ANONYMOUS_THREAD_NOT_UUID)
    return EventSourceResponse(
        chat_events(graph, thread_id=payload.thread_id, message=payload.message, jwt=jwt)
    )


@router.delete("/chat/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(thread_id: str, graph: Graph, jwt: Jwt, _service_key: ServiceKey) -> Response:
    """ลบประวัติแชทของ thread นี้ — ลบได้เฉพาะของเจ้าของ JWT เท่านั้น"""
    try:
        subject = await get_act_client().get_subject(jwt)
    except TokenExpired as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, error.message_th) from error
    except ActApiError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, error.message_th) from error

    checkpointer = getattr(graph, "checkpointer", None)
    if checkpointer is None:  # pragma: no cover - lifespan สร้างให้เสมอ
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_CHECKPOINTER)

    await checkpointer.adelete_thread(thread_key(subject, thread_id))
    logger.info("chat thread deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
