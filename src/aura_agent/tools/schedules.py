"""tool: `search_activities`"""

from datetime import date
from typing import Annotated, Any, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .. import clock
from ..data import get_act_client
from ..processing import filter_eligible, format_schedules
from .context import BAD_DATE_MESSAGE, NO_STUDENT_MESSAGE, jwt_from, student_from


@tool
async def search_activities(
    phase: Literal["open", "upcoming"] | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """ค้นหารอบกิจกรรมที่นักศึกษาคนนี้สมัครได้ (คัดรอบที่เต็มและรอบที่หมดเวลารับสมัครออกแล้ว)

    **ต้องเรียกก่อนตอบทุกครั้งที่ผู้ใช้พูดถึงรายการกิจกรรม** เพราะชื่อกิจกรรม วันที่จัด ชั่วโมง
    และที่นั่งว่าง ไม่ได้อยู่ในบทสนทนา เช่น มีกิจกรรมอะไรบ้าง, มีอะไรเปิดรับสมัคร,
    กิจกรรมชื่อนี้จัดวันไหน, เดือนหน้ามีอะไร, กิจกรรมนี้ยังสมัครได้ไหม,
    มีกิจกรรมสำหรับนักศึกษาเทียบโอนหรือคณะของฉันไหม

    phase: "open" = กำลังเปิดรับสมัคร, "upcoming" = ยังไม่เปิดรับสมัครแต่กำลังจะเปิด, ไม่ระบุ = ทั้งหมด
    keyword: คำค้นในชื่อกิจกรรม เช่น "จิตอาสา"
    date_from, date_to: ช่วงวันที่ **จัดกิจกรรม** รูปแบบ YYYY-MM-DD (ปี ค.ศ.) เช่น 2026-11-05
    """
    student = student_from(state)
    if student is None:
        return NO_STUDENT_MESSAGE

    try:
        activity_from = _parse_date(date_from)
        activity_to = _parse_date(date_to)
    except ValueError as error:
        return str(error)

    schedules = await get_act_client().get_schedules(
        jwt_from(config),
        phase=phase,
        date_from=activity_from,
        date_to=activity_to,
        search=keyword,
    )
    eligible = filter_eligible(schedules, student, clock.today())
    return format_schedules(eligible)


def _parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError(BAD_DATE_MESSAGE.format(value=value)) from error
