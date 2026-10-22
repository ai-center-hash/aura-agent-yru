"""tool: `recommend_activities`"""

from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .. import clock
from ..data import NoActivityFrame, get_act_client
from ..processing import (
    analyze_gaps,
    filter_eligible,
    format_recommendations,
    recommend,
)
from .context import jwt_from, personal_data_refusal, student_from

ALREADY_COMPLETE_MESSAGE = "ครบตามเกณฑ์ทุกหมวดแล้ว ไม่มีหมวดที่ต้องเก็บเพิ่ม"
NO_FRAME_MESSAGE = (
    "แนะนำกิจกรรมไม่ได้ เพราะยังไม่มีกรอบกิจกรรมสำหรับนักศึกษาคนนี้ ({reason})"
    " จึงไม่รู้ว่าต้องเก็บหมวดไหน ให้แนะนำติดต่อกองพัฒนานักศึกษา"
    " ถ้าผู้ใช้อยากดูกิจกรรมที่เปิดรับสมัคร ให้ใช้การค้นหากิจกรรมแทน"
)
NO_MATCH_MESSAGE = (
    "ยังไม่มีรอบกิจกรรมที่สมัครได้และตรงกับหมวดที่ยังขาด (หมวดที่ขาด: {gaps}) แนะนำให้ติดตามประกาศกิจกรรมใหม่อีกครั้ง"
)


@tool
async def recommend_activities(
    *,
    state: Annotated[dict[str, Any], InjectedState],
    config: RunnableConfig,
) -> str:
    """แนะนำรอบกิจกรรมที่ช่วยให้นักศึกษาคนนี้ครบตามเกณฑ์ เรียงจากที่ควรสมัครก่อน

    **ต้องเรียกก่อนตอบทุกครั้งที่ผู้ใช้ขอคำแนะนำกิจกรรม** เพราะต้องรู้ว่ามีรอบไหนเปิดอยู่จริง
    เช่น แนะนำกิจกรรมให้ครบหน่อย, ควรสมัครอะไรก่อน, จะเก็บหมวดที่ขาดได้จากที่ไหน,
    มีกิจกรรมไหนที่ต้องเช็คเงื่อนไขก่อนสมัคร
    """
    student = student_from(state)
    if refusal := personal_data_refusal(student, "หมวดที่ต้องเก็บหรือกิจกรรมที่แนะนำ"):
        return refusal

    client = get_act_client()
    jwt = jwt_from(config)

    try:
        report = analyze_gaps(await client.get_my_summary(jwt))
    except NoActivityFrame as missing:
        return NO_FRAME_MESSAGE.format(reason=missing.detail or missing.message_th)
    if report.is_complete:
        return ALREADY_COMPLETE_MESSAGE

    schedules = await client.get_schedules(jwt)
    eligible = filter_eligible(schedules, student, clock.today())
    recommendations = recommend(report.gaps, eligible)
    if not recommendations:
        gaps = ", ".join(gap.category_name for gap in report.gaps)
        return NO_MATCH_MESSAGE.format(gaps=gaps)

    return format_recommendations(recommendations)
