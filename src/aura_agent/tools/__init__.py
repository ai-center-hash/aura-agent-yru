"""③ Tools: เครื่องมือที่ LLM เรียกได้ (Phase 3)

tool ทุกตัว
- คืน **string เสมอ** (ถ้าเป็น error ที่ผู้ใช้แก้ไขได้ ให้คืนข้อความอธิบาย)
- ไม่รับรหัสนักศึกษาหรือ user_id เป็น parameter — ตัวตนมาจาก `state["student"]` และ JWT จาก config
- `TokenExpired` / `UpstreamUnavailable` ปล่อยให้ขึ้นไปจัดการที่ชั้น API
"""

from .context import NO_STUDENT_MESSAGE, jwt_from, student_from
from .progress import get_my_progress
from .recommend import recommend_activities
from .registrations import get_my_registrations
from .schedules import search_activities

TOOLS = [
    get_my_progress,
    search_activities,
    recommend_activities,
    get_my_registrations,
]

# ข้อความสถานะที่ API ส่งเป็น `event: status` ตอนเริ่มเรียก tool (docs/01-api-contract.md)
TOOL_STATUS = {
    "get_my_progress": "กำลังตรวจสอบความคืบหน้า...",
    "search_activities": "กำลังค้นหากิจกรรม...",
    "recommend_activities": "กำลังหากิจกรรมที่เหมาะกับคุณ...",
    "get_my_registrations": "กำลังดูประวัติการลงทะเบียน...",
}

__all__ = [
    "NO_STUDENT_MESSAGE",
    "TOOLS",
    "TOOL_STATUS",
    "get_my_progress",
    "get_my_registrations",
    "jwt_from",
    "recommend_activities",
    "search_activities",
    "student_from",
]
