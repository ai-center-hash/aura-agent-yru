"""แปลงประวัติการลงทะเบียนเป็นข้อความสถานะภาษาไทย และนาที → ชั่วโมง

status ของ Activity API: 1 ลงทะเบียนแล้ว · 4 เช็คอินแล้ว · 5 เข้าร่วมสมบูรณ์ · 6 ยกเลิก
"""

from typing import Literal

from ..data.schemas import Registration
from .models import RegistrationView

HOUR_DIGITS = 1
MINUTES_PER_HOUR = 60
CANCELLED_STATUS = 6

RegistrationFilter = Literal["registered", "checked_in", "completed", "cancelled"]

STATUS_LABELS: dict[int, str] = {
    1: "ลงทะเบียนแล้ว",
    4: "เช็คอินแล้ว",
    5: "เข้าร่วมสมบูรณ์",
    6: "ยกเลิก",
}

FILTER_TO_STATUS: dict[str, int] = {
    "registered": 1,
    "checked_in": 4,
    "completed": 5,
    "cancelled": 6,
}

UNKNOWN_TITLE = "(ไม่ทราบชื่อกิจกรรม)"


def map_registrations(
    registrations: list[Registration], status: RegistrationFilter | None = None
) -> list[RegistrationView]:
    """แปลงเป็น `RegistrationView` โดยคงลำดับเดิม (API เรียงจากที่ลงทะเบียนล่าสุด)

    `status` ที่ไม่รู้จักถือว่าไม่กรอง เพราะค่ามาจาก LLM ซึ่งพิมพ์ผิดได้
    """
    wanted = FILTER_TO_STATUS.get(status) if status else None

    views: list[RegistrationView] = []
    for registration in registrations:
        if wanted is not None and registration.status != wanted:
            continue
        views.append(
            RegistrationView(
                title=registration.activity.title if registration.activity else UNKNOWN_TITLE,
                status=registration.status,
                status_label=status_label(registration.status),
                activity_start_date=(
                    registration.schedule.activity_start_date if registration.schedule else None
                ),
                registered_at=registration.registered_at,
                checkin_at=registration.checkin_at,
                attendance_hours=attendance_hours(registration.attendance_minutes),
            )
        )
    return views


def status_label(status: int) -> str:
    return STATUS_LABELS.get(status, f"สถานะอื่น ({status})")


def attendance_hours(minutes: int | None) -> float | None:
    """นาทีที่เข้าร่วม → ชั่วโมง (None เมื่อยังไม่มีข้อมูล เช่น เช็คอินแล้วแต่ยังไม่เช็คเอาท์)"""
    if minutes is None:
        return None
    return round(minutes / MINUTES_PER_HOUR, HOUR_DIGITS)
