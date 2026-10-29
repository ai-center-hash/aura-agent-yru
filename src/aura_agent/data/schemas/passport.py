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
    position_name: str | None = None  # ของบุคลากร เช่น "อาจารย์"
    # รหัสอ้างอิงของผู้ใช้ในระบบบุคลากร/ทะเบียน · ของอาจารย์ใช้จับคู่กับ `advisor_type_ref_id` ของนักศึกษา
    # (claim `cid` ซึ่งเป็นเลขบัตรประชาชน ห้ามประกาศเพิ่มในนี้)
    user_type_id: str | None = None

    @field_validator("sub", "user_type_id", mode="before")
    @classmethod
    def _id_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value

    @property
    def login(self) -> str | None:
        """ชื่อบัญชี: รหัสนักศึกษา 9 หลัก หรือของบุคลากรเป็นแบบ `ชื่อ.อักษร`"""
        return self.username or self.preferred_username

    @property
    def student_code(self) -> str | None:
        """รหัสนักศึกษา 9 หลัก — ใช้เป็นตัวตนกับ Activity API"""
        return self.login

    @property
    def display(self) -> str:
        return self.display_name or self.name or "ไม่ทราบชื่อ"

    @property
    def is_student(self) -> bool:
        return self.user_type == "student"

    @property
    def is_staff(self) -> bool:
        """บุคลากร (อาจารย์ เจ้าหน้าที่) · `user_type` อื่นที่ไม่รู้จักไม่ใช่ทั้งนักศึกษาและบุคลากร
        จึงไม่ได้สิทธิ์ดูข้อมูลของใคร (ปิดไว้ก่อน ไม่ถือว่า "ไม่ใช่นักศึกษา = บุคลากร")
        """
        return self.user_type == "staff"
