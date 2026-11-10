"""tool ของอาจารย์ที่ปรึกษา: `list_my_advisees`, `get_advisee_progress`

**ข้อยกเว้นของกฎ "tool ห้ามรับรหัสนักศึกษา"** (ตกลงกับผู้ดูแลโปรเจกต์ 2026-10-22)
`get_advisee_progress` รับรหัสนักศึกษาได้ เพราะ `ActClient.get_advisee_summary` ตรวจทุกครั้งว่ารหัสนั้น
อยู่ในรายชื่อที่ปรึกษาของเจ้าของ token (ระบุอาจารย์จาก Passport ไม่ใช่จากข้อความ) ไม่อยู่ → ไม่ดึงข้อมูลเลย
ยกเว้นผู้ดูแลระบบกิจกรรม (role `act-admin`/`superadmin` · ตัดสิน 2026-10-29, ชื่อ role 2026-11-09)
ซึ่ง `ActClient.get_student_summary_as_admin` ตรวจ `is_admin` ซ้ำทุกครั้งก่อนดึง และบันทึก audit log
ผู้ใช้ทุกบทบาทเห็น tool ชุดเดียวกัน (ตัดสิน 2026-10-22) tool จึงเช็คบทบาทเองทุกครั้ง
"""

import re
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .. import clock
from ..config import get_settings
from ..data import NoActivityFrame, NotYourAdvisee, UpstreamNotFound, get_act_client
from ..processing import (
    analyze_gaps,
    filter_for_cohort,
    filter_open,
    format_advisee_progress,
    format_advisees,
    format_schedules,
)
from ..processing.formatter import COHORT_SCHEDULES_NOTE
from .context import LOGIN_REQUIRED_MESSAGE, NO_STUDENT_MESSAGE, jwt_from, student_from

STUDENT_CODE = re.compile(r"^\d{9,10}$")
# "นักศึกษารหัส 67" = รุ่นปีที่เข้า ไม่ใช่รหัสนักศึกษาคนใดคนหนึ่ง (AI Connect/eval 2026-11-10:
# บุคลากรถาม "นักศึกษารหัส 67 สมัครกิจกรรมอะไรได้บ้าง" แล้วโมเดลเรียก tool นี้ด้วย "67")
COHORT_CODE = re.compile(r"^\d{2}$")

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
ADMIN_NO_FRAME_MESSAGE = "ระบบกิจกรรมยังไม่มีกรอบกิจกรรมสำหรับนักศึกษา {code} ({reason}) จึงยังดูความคืบหน้าไม่ได้"
NOT_FOUND_MESSAGE = "ไม่พบรหัสนักศึกษา {code} ในระบบกิจกรรม ให้บอกผู้ใช้ว่าไม่พบรหัสนี้ และห้ามเดาข้อมูล"


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
    ขอรายชื่อทั้งหมด, หรือเมื่ออาจารย์พูดถึงนักศึกษาด้วยชื่อ (ใช้รายชื่อนี้หารหัสก่อนเรียก get_advisee_progress)

    only_incomplete: True = แสดงเฉพาะคนที่ยังไม่ครบตามเกณฑ์
    """
    student = student_from(state)
    if student is None:
        return NO_STUDENT_MESSAGE
    if student.is_anonymous:
        return LOGIN_REQUIRED_MESSAGE
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
    if student.is_anonymous:
        return LOGIN_REQUIRED_MESSAGE
    if student.is_student:
        return STAFF_ONLY_MESSAGE

    code = (student_code or "").strip()
    if COHORT_CODE.match(code):
        # โมเดลไม่ยอมเรียก search_activities ต่อเอง (eval search-26) จึงตอบรอบกิจกรรมของรุ่นนี้ให้เลย
        return await _cohort_schedules(code)
    if not STUDENT_CODE.match(code):
        return BAD_CODE_MESSAGE.format(value=student_code)

    client = get_act_client()
    jwt = jwt_from(config)
    as_admin = False
    try:
        try:
            advisee, summary = await client.get_advisee_summary(jwt, code)
        except NotYourAdvisee:
            # ไม่อยู่ในที่ปรึกษา: ดูต่อได้เฉพาะผู้ดูแลระบบ (get_student_summary_as_admin ตรวจซ้ำอีกชั้น)
            if not await client.is_admin(jwt):
                return NOT_ADVISEE_MESSAGE.format(code=code)
            as_admin = True
            advisee, summary = await client.get_student_summary_as_admin(jwt, code)
    except UpstreamNotFound:
        return NOT_FOUND_MESSAGE.format(code=code)
    except NoActivityFrame as missing:
        message = ADMIN_NO_FRAME_MESSAGE if as_admin else NO_FRAME_MESSAGE
        return message.format(code=code, reason=missing.detail or missing.message_th)
    return format_advisee_progress(advisee, analyze_gaps(summary), as_admin=as_admin)


async def _cohort_schedules(cohort: str) -> str:
    """รอบที่ยังรับสมัครซึ่งนักศึกษารหัส `cohort` สมัครได้ (ข้อมูลสาธารณะ ไม่แนบ token)"""
    schedules = await get_act_client().get_schedules("")
    items = filter_for_cohort(filter_open(schedules, clock.today()), cohort)
    listing = format_schedules(items, for_staff=True, web_url=get_settings().act_web_base_url)
    header, _, rest = listing.partition("\n")
    note = COHORT_SCHEDULES_NOTE.format(cohort=cohort)
    return "\n".join(part for part in (header, note, rest) if part)
