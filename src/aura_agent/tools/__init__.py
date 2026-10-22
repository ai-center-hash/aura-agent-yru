"""③ Tools: เครื่องมือที่ LLM เรียกได้ (Phase 3)

tool ทุกตัว
- คืน **string เสมอ** (ถ้าเป็น error ที่ผู้ใช้แก้ไขได้ ให้คืนข้อความอธิบาย)
- ไม่รับรหัสนักศึกษาหรือ user_id เป็น parameter — ตัวตนมาจาก `state["student"]` และ JWT จาก config
  (ข้อยกเว้นเดียว: `get_advisee_progress` ของอาจารย์ ซึ่งตรวจรหัสกับรายชื่อที่ปรึกษาทุกครั้ง ดู advisees.py)
- LLM เห็นชุด tool ตามบทบาท (`tools_for`) นักศึกษาไม่เห็น tool ของอาจารย์ และกลับกัน
- `TokenExpired` / `UpstreamUnavailable` ปล่อยให้ขึ้นไปจัดการที่ชั้น API
"""

from ..processing import StudentProfile
from .advisees import get_advisee_progress, list_my_advisees
from .context import NO_STUDENT_MESSAGE, jwt_from, student_from
from .progress import get_my_progress
from .recommend import recommend_activities
from .registrations import get_my_registrations
from .schedules import search_activities

STUDENT_TOOLS = [
    get_my_progress,
    search_activities,
    recommend_activities,
    get_my_registrations,
]
STAFF_TOOLS = [
    search_activities,
    list_my_advisees,
    get_advisee_progress,
]
# ทุกตัวที่ ToolNode รันได้ (LLM เห็นแค่ชุดตามบทบาท แต่ tool ก็เช็คบทบาทซ้ำเอง)
TOOLS = [*STUDENT_TOOLS, list_my_advisees, get_advisee_progress]


def tools_for(student: StudentProfile | None) -> list:
    """ชุด tool ที่ bind ให้ LLM ตามบทบาทของผู้ใช้ (ไม่รู้บทบาท = ชุดนักศึกษา ซึ่งไม่มีข้อมูลคนอื่น)"""
    if student is not None and not student.is_student:
        return STAFF_TOOLS
    return STUDENT_TOOLS


# ข้อความสถานะที่ API ส่งเป็น `event: status` ตอนเริ่มเรียก tool (docs/01-api-contract.md)
TOOL_STATUS = {
    "get_my_progress": "กำลังตรวจสอบความคืบหน้า...",
    "search_activities": "กำลังค้นหากิจกรรม...",
    "recommend_activities": "กำลังหากิจกรรมที่เหมาะกับคุณ...",
    "get_my_registrations": "กำลังดูประวัติการลงทะเบียน...",
    "list_my_advisees": "กำลังดูรายชื่อนักศึกษาในที่ปรึกษา...",
    "get_advisee_progress": "กำลังตรวจสอบความคืบหน้าของนักศึกษา...",
}

__all__ = [
    "NO_STUDENT_MESSAGE",
    "STAFF_TOOLS",
    "STUDENT_TOOLS",
    "TOOLS",
    "TOOL_STATUS",
    "get_advisee_progress",
    "list_my_advisees",
    "tools_for",
    "get_my_progress",
    "get_my_registrations",
    "jwt_from",
    "recommend_activities",
    "search_activities",
    "student_from",
]
