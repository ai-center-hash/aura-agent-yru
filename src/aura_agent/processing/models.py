"""ผลลัพธ์ของชั้น processing — dataclass อ่านอย่างเดียว ไม่มี I/O

ชั้นนี้เป็น pure function ทั้งหมด ฟังก์ชันที่ต้องรู้ "วันนี้" ให้รับ `today` เป็น argument
"""

from dataclasses import dataclass
from datetime import datetime

from ..data.schemas import PassportUser, Schedule, SummaryUser

MANDATORY_KEYWORD = "บังคับ"


@dataclass(frozen=True, slots=True)
class StudentProfile:
    """ตัวตนของผู้ใช้ที่คุยอยู่ — มาจาก token เสมอ (ผ่าน summary ของ Activity API หรือ Passport)

    เก็บเท่าที่ใช้ตัดสินสิทธิ์สมัครและใช้ทักทาย ไม่เก็บอีเมล
    `id` (user_id ของ Activity API) เป็น None เมื่อนักศึกษายังไม่มีกรอบกิจกรรม
    เพราะตอนนั้น API ไม่คืนข้อมูลผู้ใช้มาให้ จึงดูประวัติการลงทะเบียนไม่ได้
    `is_student=False` คือบุคลากร (อาจารย์ เจ้าหน้าที่ แอดมิน) ซึ่งไม่มีกรอบกิจกรรมและรหัสนักศึกษา
    """

    id: int | None
    name: str
    faculty: str | None = None
    major: str | None = None
    student_status: str = "normal"
    student_id: str | None = None
    is_student: bool = True
    position: str | None = None  # ตำแหน่งของบุคลากร เช่น "อาจารย์" (นักศึกษาเป็น None)

    @property
    def is_transfer(self) -> bool:
        return self.student_status == "transfer"

    @classmethod
    def from_user(cls, user: SummaryUser) -> "StudentProfile":
        return cls(
            id=user.id,
            name=user.name,
            faculty=user.faculty,
            major=user.major,
            student_status=user.student_status,
            student_id=user.student_id,
        )

    @classmethod
    def from_passport(cls, user: PassportUser) -> "StudentProfile":
        """ใช้เมื่อไม่มีกรอบกิจกรรม (นักศึกษาที่ยังไม่มีกรอบ หรือบุคลากร)

        รู้ชื่อและหน่วยงาน แต่ไม่รู้ user_id กับประเภทนักศึกษา
        username ของบุคลากรไม่ใช่รหัสนักศึกษา จึงไม่เก็บเป็น `student_id`
        """
        return cls(
            id=None,
            name=user.display,
            faculty=user.org_unit_1_name,
            student_id=user.student_code if user.is_student else None,
            is_student=user.is_student,
            position=None if user.is_student else user.position_name,
        )


@dataclass(frozen=True, slots=True)
class Gap:
    """หมวดที่ยังไม่ครบเกณฑ์"""

    category_id: int
    category_name: str
    type_name: str | None
    missing_activities: int
    missing_hours: float

    @property
    def is_mandatory(self) -> bool:
        return is_mandatory_category(self.category_name, self.type_name)


@dataclass(frozen=True, slots=True)
class PassedItem:
    """หมวดที่ผ่านเกณฑ์แล้ว"""

    category_id: int
    category_name: str
    type_name: str | None
    count: int
    total_hours: float

    @property
    def is_mandatory(self) -> bool:
        return is_mandatory_category(self.category_name, self.type_name)


def is_mandatory_category(category_name: str | None, type_name: str | None) -> bool:
    """หมวดบังคับหรือไม่ — ดูคำว่า "บังคับ" ทั้งในชื่อหมวดและชื่อประเภท

    ข้อมูลจริงเก็บไว้ที่**ชื่อหมวด** (หมวด "กิจกรรมบังคับ" ประเภท "กิจกรรมมหาวิทยาลัย")
    ส่วนตัวอย่างในคู่มือเก็บไว้ที่ชื่อประเภท ("กิจกรรมบังคับ") จึงต้องดูทั้งสองที่
    ประเภท "กิจกรรมมหาวิทยาลัย" เองบังคับหรือไม่ยังไม่รู้ (Q9 ใน HANDOFF) จึงไม่เดา
    """
    return any(MANDATORY_KEYWORD in (text or "") for text in (category_name, type_name))


@dataclass(frozen=True, slots=True)
class ProgressReport:
    """สรุปความคืบหน้าทั้งกรอบ"""

    frame_title: str | None
    overall_status: str | None
    total_activities: int
    total_hours: float
    passed_items: list[PassedItem]
    gaps: list[Gap]

    @property
    def is_complete(self) -> bool:
        return not self.gaps

    @property
    def mandatory_gaps(self) -> list[Gap]:
        return [gap for gap in self.gaps if gap.is_mandatory]


@dataclass(frozen=True, slots=True)
class EligibleSchedule:
    """รอบที่นักศึกษาคนนี้สมัครได้

    `eligibility_uncertain=True` เมื่อรอบนั้นจำกัดกลุ่มเป้าหมายด้วยเงื่อนไขที่เรายังเทียบไม่ได้
    (ตอนนี้คือรุ่นปี ดู Q4 ใน HANDOFF) formatter จะติดป้ายให้ผู้ใช้ไปตรวจเองก่อนสมัคร
    """

    schedule: Schedule
    eligibility_uncertain: bool = False
    uncertain_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Recommendation:
    """รอบที่ช่วยปิดช่องว่างของหมวดที่ขาด"""

    schedule: Schedule
    gap: Gap
    covers_hours: float
    eligibility_uncertain: bool = False


@dataclass(frozen=True, slots=True)
class RegistrationView:
    """ประวัติการลงทะเบียน 1 รายการในรูปแบบที่พร้อมแสดง"""

    title: str
    status: int
    status_label: str
    activity_start_date: datetime | None
    registered_at: datetime | None
    checkin_at: datetime | None
    attendance_hours: float | None
