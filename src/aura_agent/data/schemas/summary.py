"""Endpoint A · `GET /v1/report/summary/me` — ความคืบหน้ากิจกรรมของนักศึกษาที่ login

โครงสร้าง: data.user / data.frame / data.summary / data.categories[].frame_items[]
ชั้นนี้แปลงข้อมูลเป็น object อย่างเดียว การเลือกเกณฑ์ normal/transfer เป็นงานของ processing (Phase 2)
"""

from datetime import date, datetime

from pydantic import Field

from .base import ActModel


class FrameRequirement(ActModel):
    """เกณฑ์ขั้นต่ำของ frame item แยกตามประเภทนักศึกษา"""

    normal_activity_min: int = 0
    normal_hour_min: float = 0
    transfer_activity_min: int = 0
    transfer_hour_min: float = 0


class AttendedActivity(ActModel):
    """กิจกรรมที่นักศึกษาเข้าร่วมแล้วและถูกนับในหมวดนี้"""

    id: int | None = None
    title: str
    duration_hours: float | None = None
    attendance_hours: float | None = None
    checkin_at: datetime | None = None
    checkout_at: datetime | None = None


class FrameItem(ActModel):
    """เกณฑ์ 1 ข้อในกรอบกิจกรรม พร้อมผลที่นักศึกษาทำได้แล้ว"""

    id: int | None = None
    category_id: int
    category_name: str | None = None
    requirement: FrameRequirement = Field(default_factory=FrameRequirement)
    count: int = 0
    total_hours: float = 0
    is_passed: bool = False
    activities: list[AttendedActivity] = Field(default_factory=list)


class SummaryCategory(ActModel):
    """หมวดกิจกรรม เช่น กิจกรรมบังคับด้านคุณธรรมจริยธรรม"""

    category_id: int
    category_name: str
    type_id: int | None = None
    type_name: str | None = None
    frame_items: list[FrameItem] = Field(default_factory=list)


class ActivityFrame(ActModel):
    """กรอบกิจกรรมที่นักศึกษาคนนี้ถูกเทียบเกณฑ์ด้วย"""

    id: int
    title: str
    start_date: date | None = None
    end_date: date | None = None


class SummaryTotals(ActModel):
    """ยอดรวมทั้งกรอบ"""

    total_activities: int = 0
    total_hours: float = 0
    overall_status: str | None = None


class SummaryUser(ActModel):
    """ตัวตนของนักศึกษา — `id` คือ user_id แหล่งเดียวที่ใช้กับ endpoint C ได้

    ไม่ประกาศ `email` ไว้เพราะไม่ได้ใช้ (ActModel จะทิ้งให้เอง)
    """

    id: int
    name: str
    student_id: str | None = None
    faculty: str | None = None
    major: str | None = None
    level: str | None = None
    student_status: str = "normal"


class StudentSummary(ActModel):
    """ค่าใน `data` ของ endpoint A"""

    user: SummaryUser
    frame: ActivityFrame | None = None
    summary: SummaryTotals = Field(default_factory=SummaryTotals)
    categories: list[SummaryCategory] = Field(default_factory=list)
