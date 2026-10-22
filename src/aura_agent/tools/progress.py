"""tool: `get_my_progress`"""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..data import NoActivityFrame, NotAStudent, get_act_client
from ..processing import analyze_gaps, format_no_frame, format_progress
from .context import NOT_STUDENT_MESSAGE, jwt_from


@tool
async def get_my_progress(*, config: RunnableConfig) -> str:
    """ดึงความคืบหน้ากิจกรรมล่าสุดของนักศึกษาคนนี้จากระบบ บอกว่าผ่านหมวดไหนแล้วและยังขาดกี่กิจกรรมกี่ชั่วโมง

    ใช้เมื่อผู้ใช้ขอข้อมูลล่าสุด ขอให้ตรวจสอบใหม่ หรืออยากรู้ว่าเคยเข้ากิจกรรมอะไรไปแล้ว
    ถ้าผู้ใช้ถามเรื่องหมวดที่ขาดแบบทั่วไป ให้ตอบจากส่วน [ความคืบหน้า] ที่มีอยู่แล้วโดยไม่ต้องเรียกเครื่องมือนี้
    """
    try:
        summary = await get_act_client().get_my_summary(jwt_from(config))
    except NoActivityFrame as missing:
        return format_no_frame(missing.detail)
    except NotAStudent:
        return NOT_STUDENT_MESSAGE.format(subject="ความคืบหน้ากิจกรรม")
    return format_progress(analyze_gaps(summary))
