"""โหลด system prompt จาก `prompts/system_prompt.th.md` แล้วเติมค่า

ไฟล์ prompt อยู่นอกแพ็กเกจเพื่อให้แก้ได้โดยไม่ต้องแตะโค้ด
**แก้ไฟล์นั้นแล้วต้องรัน eval (Phase 5) ทุกครั้ง**
"""

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from ..processing import StudentProfile, thai_date

PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "system_prompt.th.md"

_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)

UNKNOWN_NAME = "ไม่ทราบชื่อ"
UNKNOWN_FIELD = "ไม่ระบุ"
STAFF_TYPE = "บุคลากร (ไม่ใช่นักศึกษา)"
NO_PROGRESS_TEXT = "[ความคืบหน้า] ยังไม่มีข้อมูล ถ้าผู้ใช้ถามเรื่องความคืบหน้าให้เรียก get_my_progress ก่อนตอบ"


@lru_cache
def load_template(path: str | None = None) -> str:
    """อ่านไฟล์ prompt แล้วตัดส่วน comment สำหรับผู้ดูแลออก"""
    text = Path(path or PROMPT_PATH).read_text(encoding="utf-8")
    return _LEADING_COMMENT.sub("", text).strip()


def render_system_prompt(
    today: date,
    student: StudentProfile | None,
    progress_text: str | None,
    *,
    template: str | None = None,
) -> str:
    """เติมค่าลง prompt ใหม่ทุกครั้งที่เรียก LLM (ไม่เก็บลง messages)"""
    return (template or load_template()).format(
        today=f"{thai_date(today)} ({today.isoformat()})",
        student_name=student.name if student else UNKNOWN_NAME,
        student_faculty=(student.faculty if student else None) or UNKNOWN_FIELD,
        student_major=(student.major if student else None) or UNKNOWN_FIELD,
        student_type=_student_type(student),
        progress_text=progress_text or NO_PROGRESS_TEXT,
    )


def _student_type(student: StudentProfile | None) -> str:
    if student is None:
        return UNKNOWN_FIELD
    if not student.is_student:
        return STAFF_TYPE
    return "เทียบโอน" if student.is_transfer else "นักศึกษาปกติ"
