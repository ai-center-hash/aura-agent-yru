"""YRU Passport · `GET /oidc/userinfo` — ตัวตนของเจ้าของ access token"""

from pydantic import field_validator

from .base import ActModel


class PassportUser(ActModel):
    """claim ที่เราใช้จาก userinfo (เก็บเท่าที่จำเป็น ไม่เก็บอีเมลหรือเลขบัตร)"""

    sub: str
    username: str | None = None
    preferred_username: str | None = None
    user_type: str | None = None
    name: str | None = None
    display_name: str | None = None
    org_unit_1_name: str | None = None

    @field_validator("sub", mode="before")
    @classmethod
    def _sub_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value

    @property
    def student_code(self) -> str | None:
        """รหัสนักศึกษา 9 หลัก — ใช้เป็นตัวตนกับ Activity API"""
        return self.username or self.preferred_username

    @property
    def display(self) -> str:
        return self.display_name or self.name or "ไม่ทราบชื่อ"

    @property
    def is_student(self) -> bool:
        return self.user_type == "student"
