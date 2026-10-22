"""tool ของอาจารย์ที่ปรึกษา: `list_my_advisees`, `get_advisee_progress`

**ข้อยกเว้นของกฎ "tool ห้ามรับรหัสนักศึกษา"** (ตกลงกับผู้ดูแลโปรเจกต์ 2026-10-22)
`get_advisee_progress` รับรหัสนักศึกษาได้ เพราะ `ActClient.get_advisee_summary` ตรวจทุกครั้งว่ารหัสนั้น
อยู่ในรายชื่อที่ปรึกษาของเจ้าของ token (ระบุอาจารย์จาก Passport ไม่ใช่จากข้อความ) ไม่อยู่ → ไม่ดึงข้อมูลเลย
tool ทั้งสองตัว bind ให้ LLM เฉพาะตอนผู้ใช้เป็นบุคลากร (ดู `tools_for`) และเช็คซ้ำในตัว tool
"""

import re
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..data import NoActivityFrame, NotYourAdvisee, get_act_client
from ..processing import analyze_gaps, format_advisee_progress, format_advisees
from .context import NO_STUDENT_MESSAGE, jwt_from, student_from

STUDENT_CODE = re.compile(r"^\d{9,10}$")

STAFF_ONLY_MESSAGE = "ส่วนนี้ใช้ได้เฉพาะอาจารย์ที่ปรึกษา นักศึกษาดูได้เฉพาะข้อมูลของตัวเอง"
BAD_CODE_MESSAGE = (
    "รหัสนักศึกษาต้องเป็นตัวเลข 9–10 หลัก ({value}) ถ้าผู้ใช้บอกเป็นชื่อ"
    " ให้เรียก list_my_advisees ก่อนเพื่อหารหัสจากรายชื่อ"
)
NOT_ADVISEE_MESSAGE = (
    "รหัส {code} ไม่ได้อยู่ในรายชื่อนักศึกษาในที่ปรึกษาของผู้ใช้ จึงดูข้อมูลไม่ได้ ให้ปฏิเสธสุภาพ และห้ามเดาข้อมูลของนักศึกษาคนนี้"
)
NO_FRAME_MESSAGE = (
    "นักศึกษา {code} อยู่ในที่ปรึกษา แต่ระบบกิจกรรมยังไม่มีกรอบกิจกรรมสำหรับนักศึกษาคนนี้ ({reason})"
    " จึงยังดูความคืบหน้าไม่ได้"
)


@tool
async def list_my_advisees(
    only_incomplete: bool = False,
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """รายชื่อนักศึกษาในที่ปรึกษาของอาจารย์คนนี้ พร้อมจำนวนกิจกรรมที่ทำตามเกณฑ์แล้ว เรียงจากคนที่ยังขาดมากที่สุด

    **ต้องเรียกก่อนตอบทุกครั้งที่อาจารย์ถามถึงนักศึกษาในที่ปรึกษา** เพราะรายชื่อไม่ได้อยู่ในบทสนทนา
    เช่น นักศึกษาในที่ปรึกษามีใครบ้าง, มีกี่คน, ใครยังทำกิจกรรมไม่ครบ, ครบแล้วกี่คน,
    หรือเมื่ออาจารย์พูดถึงนักศึกษาด้วยชื่อ (ใช้รายชื่อนี้หารหัสก่อนเรียก get_advisee_progress)

    only_incomplete: True = แสดงเฉพาะคนที่ยังไม่ครบตามเกณฑ์
    """
    student = student_from(state)
    if student is None:
        return NO_STUDENT_MESSAGE
    if student.is_student:
        return STAFF_ONLY_MESSAGE

    advisees = await get_act_client().get_advisees(jwt_from(config))
    return format_advisees(advisees, only_incomplete=only_incomplete)


@tool
async def get_advisee_progress(
    student_code: str,
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """ความคืบหน้ากิจกรรมแบบละเอียดของนักศึกษา 1 คนในที่ปรึกษา: ผ่านหมวดไหนแล้ว ยังขาดหมวดไหน กี่ชั่วโมง

    **ต้องเรียกก่อนตอบทุกครั้งที่อาจารย์ถามรายละเอียดของนักศึกษาคนใดคนหนึ่ง**
    เช่น นักศึกษารหัสนี้ขาดหมวดไหน, คนนี้ได้กี่ชั่วโมงแล้ว
    ดูได้เฉพาะนักศึกษาที่อยู่ในที่ปรึกษาของอาจารย์คนนี้เท่านั้น

    student_code: รหัสนักศึกษา (ตัวเลข) ถ้ารู้แค่ชื่อ ให้เรียก list_my_advisees ก่อนเพื่อหารหัส
    """
    student = student_from(state)
    if student is None:
        return NO_STUDENT_MESSAGE
    if student.is_student:
        return STAFF_ONLY_MESSAGE

    code = (student_code or "").strip()
    if not STUDENT_CODE.match(code):
        return BAD_CODE_MESSAGE.format(value=student_code)

    try:
        advisee, summary = await get_act_client().get_advisee_summary(jwt_from(config), code)
    except NotYourAdvisee:
        return NOT_ADVISEE_MESSAGE.format(code=code)
    except NoActivityFrame as missing:
        return NO_FRAME_MESSAGE.format(code=code, reason=missing.detail or missing.message_th)
    return format_advisee_progress(advisee, analyze_gaps(summary))
