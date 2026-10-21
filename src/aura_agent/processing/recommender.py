"""จับคู่หมวดที่ขาดกับรอบที่สมัครได้ แล้วเรียงว่าควรสมัครอะไรก่อน

ลำดับ: กิจกรรมบังคับก่อน → วันจัดกิจกรรมใกล้ที่สุด → ปิดช่องว่างได้มากที่สุด
"""

from datetime import datetime

from ..data.schemas import Schedule
from .models import EligibleSchedule, Gap, Recommendation

HOUR_DIGITS = 1
DEFAULT_LIMIT = 5


def recommend(
    gaps: list[Gap], eligible: list[EligibleSchedule], limit: int = DEFAULT_LIMIT
) -> list[Recommendation]:
    """คืนรอบที่ช่วยปิดหมวดที่ขาด ถ้าไม่มีหมวดที่ขาดคืน list ว่าง"""
    if not gaps or limit <= 0:
        return []

    gap_by_category = {gap.category_id: gap for gap in gaps}
    candidates: list[Recommendation] = []

    for item in eligible:
        gap = gap_by_category.get(item.schedule.category_id)
        if gap is None:
            continue
        candidates.append(
            Recommendation(
                schedule=item.schedule,
                gap=gap,
                covers_hours=_covers_hours(item.schedule, gap),
                eligibility_uncertain=item.eligibility_uncertain,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            not candidate.gap.is_mandatory,
            _start_key(candidate.schedule),
            -candidate.covers_hours,
            candidate.schedule.id,
        )
    )
    return candidates[:limit]


def _covers_hours(schedule: Schedule, gap: Gap) -> float:
    """ชั่วโมงของรอบนี้ที่ช่วยปิดช่องว่างได้จริง (ไม่นับส่วนที่เกินเกณฑ์)"""
    duration = schedule.duration_hours or 0.0
    if gap.missing_hours <= 0:
        return round(duration, HOUR_DIGITS)
    return round(min(duration, gap.missing_hours), HOUR_DIGITS)


def _start_key(schedule: Schedule) -> float:
    """รอบที่ไม่บอกวันจัดให้ไปอยู่ท้ายสุด"""
    start: datetime | None = schedule.activity_start_date
    return start.timestamp() if start is not None else float("inf")
