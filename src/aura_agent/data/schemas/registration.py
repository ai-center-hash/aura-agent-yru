"""Endpoint C · `GET /v1/act/act-registrations?user_id={id}` — ประวัติการลงทะเบียน

ความหมายของ `status`: 1 ลงทะเบียนแล้ว · 4 เช็คอินแล้ว · 5 เข้าร่วมสมบูรณ์ · 6 ยกเลิก
เก็บเป็น int ดิบ ค่าที่ไม่รู้จักจะไม่ทำให้ parse พัง การแปลงเป็นข้อความไทยทำใน processing (Phase 2)
"""

from datetime import datetime

from .base import ActModel


class RegistrationActivity(ActModel):
    """กิจกรรมหลักของการลงทะเบียนนี้"""

    id: int | None = None
    title: str


class RegistrationSchedule(ActModel):
    """รอบที่ลงทะเบียนไว้"""

    id: int | None = None
    activity_start_date: datetime | None = None
    activity_end_date: datetime | None = None
    duration_minutes: int | None = None
    status: str | None = None


class Registration(ActModel):
    """การลงทะเบียน 1 รายการ

    ไม่ประกาศฟิลด์ `user`, `user_name`, `user_code` ไว้เพราะเรียกแบบกรอง user_id อยู่แล้ว
    จึงไม่ต้องเก็บชื่อหรือรหัสนักศึกษาซ้ำ (ActModel จะทิ้งให้เอง)
    """

    id: int
    activity_id: int | None = None
    schedule_id: int | None = None
    status: int
    registered_at: datetime | None = None
    checkin_at: datetime | None = None
    checkout_at: datetime | None = None
    attendance_minutes: int | None = None

    activity: RegistrationActivity | None = None
    schedule: RegistrationSchedule | None = None
