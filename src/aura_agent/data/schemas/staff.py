"""Activity API · `GET /v1/auth/users?type_in=teacher,staff,personnel` — บัญชีบุคลากรในระบบกิจกรรม

ใช้ตรวจ role `admin` ของระบบกิจกรรม (เว็บ act.yru.ac.th ใช้ `local-role:admin` ตัดสินสิทธิ์จัดการแบบเดียวกัน)
response จริงมีที่อยู่ เบอร์โทร อีเมล ฯลฯ — schema นี้ประกาศเฉพาะที่ใช้จับคู่และตรวจ role
"""

from pydantic import field_validator

from .base import ActModel


class StaffAccount(ActModel):
    """บุคลากร 1 คน · `type_ref_id` = `user_type_id` ใน Passport ของคนเดียวกัน"""

    username: str
    type: str | None = None
    type_ref_id: str | None = None
    roles: list[str] = []

    @field_validator("type_ref_id", mode="before")
    @classmethod
    def _ref_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value

    @field_validator("roles", mode="before")
    @classmethod
    def _role_names(cls, value: object) -> object:
        """ของจริงเป็น `[{"name": "admin", "display_name": ...}]` เก็บแค่ชื่อ"""
        if value is None:
            return []
        if isinstance(value, list):
            return [
                str(item.get("name")) if isinstance(item, dict) else str(item) for item in value
            ]
        return value
