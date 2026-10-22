"""Activity API · `GET /v1/auth/users` แบบกรองด้วย `advisor_type_ref_id`

รายชื่อนักศึกษาในที่ปรึกษาของอาจารย์ 1 คน (หน้าเว็บระบบกิจกรรม /auth/employees ใช้วิธีเดียวกัน)
`advisor_type_ref_id` ของนักศึกษา = `user_type_id` ใน Passport ของอาจารย์

**response จริงมีที่อยู่ เบอร์โทร อีเมล บทบาท/สิทธิ์ ฯลฯ — schema นี้ประกาศเฉพาะที่ใช้**
ฟิลด์อื่นถูกทิ้งตอน parse (`extra="ignore"`) จึงไม่ถูกเก็บใน cache และไม่ถึง LLM
"""

from pydantic import Field, field_validator

from .base import ActModel


class ActivityProgress(ActModel):
    """จำนวน**กิจกรรม**ที่นับตามเกณฑ์แล้ว (`passed`) จากที่กรอบกำหนดทั้งหมด (`total`)

    ตรวจกับข้อมูลจริง 2026-10-22: นักศึกษาที่ขาดกิจกรรมบังคับ 1 กิจกรรม ได้ 29/30 (ไม่ใช่จำนวนหมวด)
    """

    passed: int = 0
    total: int = 0

    @property
    def has_frame(self) -> bool:
        return self.total > 0

    @property
    def is_complete(self) -> bool:
        return self.has_frame and self.passed >= self.total

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.passed)


class Advisee(ActModel):
    """นักศึกษา 1 คนในที่ปรึกษา"""

    username: str  # รหัสนักศึกษา
    name: str | None = None
    prefix: str | None = None
    fname: str | None = None
    lname: str | None = None
    program: str | None = None
    student_status: str | None = None
    advisor_type_ref_id: str | None = None
    activity_summary: ActivityProgress = Field(default_factory=ActivityProgress)

    @field_validator("advisor_type_ref_id", mode="before")
    @classmethod
    def _ref_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value

    @field_validator("activity_summary", mode="before")
    @classmethod
    def _summary_or_empty(cls, value: object) -> object:
        return value if value is not None else {}

    @property
    def display_name(self) -> str:
        full = " ".join(part for part in (self.fname, self.lname) if part)
        return full or self.name or self.username
