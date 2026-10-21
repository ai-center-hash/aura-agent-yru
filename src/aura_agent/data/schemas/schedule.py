"""Endpoint B · `GET /v1/act/activity-schedules` — รอบกิจกรรม (1 แถว = 1 รอบ)

`available_slots`, `is_full`, `is_registration_open` ทาง API คำนวณมาให้แล้ว
การตัดสินว่านักศึกษาคนนี้สมัครได้ไหมเป็นงานของ processing (Phase 2)
"""

from datetime import datetime

from pydantic import Field, field_validator

from .base import ActModel


class ScheduleActivity(ActModel):
    """กิจกรรมหลักที่รอบนี้สังกัด"""

    id: int | None = None
    title: str
    organizer_name: str | None = None


class Schedule(ActModel):
    """รอบกิจกรรม 1 รอบ"""

    id: int
    activity_id: int | None = None
    type_id: int | None = None
    type_label: str | None = None
    category_id: int | None = None
    category_label: str | None = None

    registration_start_date: datetime | None = None
    registration_end_date: datetime | None = None
    activity_start_date: datetime | None = None
    activity_end_date: datetime | None = None
    duration_hours: float | None = None

    max_participants: int | None = None
    current_participants: int | None = None
    available_slots: int | None = None
    is_registration_open: bool = False
    is_full: bool = False
    is_restricted: bool = False

    target_student_codes: list[str] = Field(default_factory=list)  # รายรหัสนักศึกษาที่สมัครได้
    target_student_year_prefix: list[str] = Field(default_factory=list)
    target_faculties: list[str] = Field(default_factory=list)
    target_student_status: str | None = None

    activity: ScheduleActivity | None = None

    @field_validator(
        "target_student_codes", "target_student_year_prefix", "target_faculties", mode="before"
    )
    @classmethod
    def _as_str_list(cls, value: object) -> object:
        """รอบที่ไม่จำกัดกลุ่มเป้าหมายส่ง null มา และรหัสปีอาจมาเป็นตัวเลข (68) ไม่ใช่ string"""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return value
