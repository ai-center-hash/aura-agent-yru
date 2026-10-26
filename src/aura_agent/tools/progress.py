"""tool: `get_my_progress`"""

from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..data import NoActivityFrame, NotAStudent, get_act_client
from ..processing import analyze_gaps, format_attended, format_no_frame, format_progress
from .context import NOT_STUDENT_MESSAGE, jwt_from, personal_data_refusal, student_from

SUBJECT = "ความคืบหน้ากิจกรรม"


@tool
async def get_my_progress(
    category: str | None = None,
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """ดึงความคืบหน้ากิจกรรมล่าสุดของนักศึกษาคนนี้จากระบบ บอกว่าผ่านหมวดไหนแล้วและยังขาดกี่กิจกรรมกี่ชั่วโมง
    พร้อมรายชื่อกิจกรรมที่ถูกนับแล้วในแต่ละหมวด

    ใช้เมื่อผู้ใช้ขอข้อมูลล่าสุด ขอให้ตรวจสอบใหม่ หรืออยากรู้ว่าเคยเข้ากิจกรรมอะไรไปแล้ว
    **ต้องเรียกก่อนตอบทุกครั้งที่ผู้ใช้ถามถึงกิจกรรมที่เข้าแล้วในหมวดใดหมวดหนึ่ง** เช่น ขอดูจิตอาสาของผม,
    เข้ากิจกรรมหมวดกีฬาอะไรไปแล้วบ้าง — ชื่อกิจกรรมมักไม่มีชื่อหมวด ดูจากประวัติการลงทะเบียนไม่ได้
    ถ้าผู้ใช้ถามเรื่องหมวดที่ขาดแบบทั่วไป ให้ตอบจากส่วน [ความคืบหน้า] ที่มีอยู่แล้วโดยไม่ต้องเรียกเครื่องมือนี้

    category: คำในชื่อหมวดที่ถามถึง เช่น "จิตอาสา" ไม่ระบุ = ทุกหมวด
    """
    student = student_from(state)
    if student is not None and (refusal := personal_data_refusal(student, SUBJECT)):
        return refusal

    try:
        summary = await get_act_client().get_my_summary(jwt_from(config))
    except NoActivityFrame as missing:
        return format_no_frame(missing.detail)
    except NotAStudent:
        return NOT_STUDENT_MESSAGE.format(subject=SUBJECT)
    report = analyze_gaps(summary)
    if category and category.strip():
        # ถามเฉพาะหมวด: ให้รายชื่อกิจกรรม + สถานะของหมวดนั้นเป็นก้อนเดียว (ไม่ให้ภาพรวมกลบรายชื่อ)
        return format_attended(summary, category=category, report=report)
    return f"{format_progress(report)}\n\n{format_attended(summary)}"
