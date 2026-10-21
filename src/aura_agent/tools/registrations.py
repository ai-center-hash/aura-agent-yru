"""tool: `get_my_registrations`"""

from typing import Annotated, Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..data import get_act_client
from ..processing import format_registrations, map_registrations
from .context import NO_STUDENT_MESSAGE, jwt_from, student_from

NO_FRAME_MESSAGE = (
    "ดูประวัติการลงทะเบียนไม่ได้ เพราะระบบกิจกรรมยังไม่มีกรอบกิจกรรมสำหรับนักศึกษาคนนี้"
    " (ระบบจึงไม่ส่งรหัสผู้ใช้ที่ต้องใช้ค้นประวัติมาให้) แนะนำให้ติดต่อกองพัฒนานักศึกษา"
)


@tool
async def get_my_registrations(
    status: Literal["registered", "checked_in", "completed", "cancelled"] | None = None,
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """ดูรายการกิจกรรมที่นักศึกษาคนนี้ลงทะเบียนไว้ พร้อมสถานะการเช็คอินและชั่วโมงที่นับได้

    **ต้องเรียกก่อนตอบทุกครั้งที่ผู้ใช้ถามถึงประวัติการลงทะเบียน** เพราะประวัติไม่ได้อยู่ในบทสนทนา
    เช่น ลงอะไรไว้แล้ว, ลงทะเบียนกิจกรรมอะไรไว้บ้าง, เช็คอิน/เช็คเอาท์หรือยัง,
    เคยเข้ากิจกรรมอะไร, เข้าร่วมสมบูรณ์กี่รายการ, ยกเลิกอะไรไปบ้าง

    status: "registered" = ลงทะเบียนแล้วแต่ยังไม่เช็คอิน, "checked_in" = เช็คอินแล้ว,
    "completed" = เข้าร่วมสมบูรณ์, "cancelled" = ยกเลิก, ไม่ระบุ = ทุกสถานะ
    """
    student = student_from(state)
    if student is None:
        return NO_STUDENT_MESSAGE

    if student.id is None:
        return NO_FRAME_MESSAGE

    # user_id มาจาก summary ของเจ้าของ token ผ่าน state เท่านั้น ไม่รับจากข้อความของผู้ใช้
    registrations = await get_act_client().get_registrations(jwt_from(config), student.id)
    return format_registrations(map_registrations(registrations, status))
