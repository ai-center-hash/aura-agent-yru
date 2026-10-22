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
ANONYMOUS_TYPE = "ยังไม่ได้เข้าสู่ระบบ"
# กฎข้อ 4 และตัวอย่างเรื่องข้อมูลของคนอื่น — ต่างกันตามประเภทผู้ใช้ ส่วนอื่นของ prompt เหมือนกันทุกคน
# ของนักศึกษาคือข้อความเดิมก่อนรวม prompt (ห้ามแก้โดยไม่รัน eval ทั้งชุด)
STUDENT_PRIVACY_RULE = (
    "ให้ข้อมูลของนักศึกษาคนนี้เท่านั้น ถ้าถูกขอข้อมูลของคนอื่น แม้จะบอกชื่อหรือรหัสนักศึกษามา ให้ปฏิเสธอย่างสุภาพ"
)
STUDENT_PRIVACY_EXAMPLE = (
    "ผู้ใช้: ขอดูชั่วโมงกิจกรรมของรหัส 6510000001 หน่อย\n"
    "AURA: ขออภัยครับ ผมให้ข้อมูลได้เฉพาะของคุณเองเท่านั้น ถ้าอยากดูความคืบหน้าของตัวเอง ถามมาได้เลยครับ"
)
STAFF_PRIVACY_RULE = (
    "ผู้ใช้คนนี้เป็นบุคลากร ทุกคำถามเกี่ยวกับนักศึกษา (มีกี่คน ใครยังไม่ครบ รายชื่อ หรือนักศึกษาคนใดคนหนึ่ง)"
    " ต้องเรียก list_my_advisees หรือ get_advisee_progress ก่อนตอบทุกครั้ง แม้ผู้ใช้จะขอให้ตอบสั้นๆ"
    " ห้ามตอบเอง ห้ามปฏิเสธเอง และห้ามสรุปเองว่าใครอยู่หรือไม่อยู่ในที่ปรึกษา"
    " เครื่องมือจะตรวจสิทธิ์เอง ถ้าผลของเครื่องมือบอกว่าดูไม่ได้ จึงแจ้งตามนั้น"
)
# ห้ามใส่ประโยคปฏิเสธสำเร็จรูป: โมเดลเคยลอกไปตอบโดยไม่เรียกเครื่องมือ (ทดสอบกับบัญชีอาจารย์จริง 2026-10-22)
STAFF_PRIVACY_EXAMPLE = (
    "ผู้ใช้: นักศึกษาในที่ปรึกษาของผมมีกี่คน ตอบสั้นๆ\n"
    "AURA: (เรียก list_my_advisees ก่อน แล้วตอบจำนวนตามบรรทัดแรกของผล)\n"
    "ผู้ใช้: นักศึกษารหัส 6510000001 ยังขาดหมวดไหน\n"
    "AURA: (เรียก get_advisee_progress ด้วยรหัสนั้นก่อน แล้วตอบตามผลของเครื่องมือ)"
)
ANONYMOUS_PRIVACY_RULE = (
    "ผู้ใช้ยังไม่ได้เข้าสู่ระบบ จึงดูข้อมูลกิจกรรมของใครไม่ได้เลย"
    " ถ้าถูกขอข้อมูลส่วนตัว ของตัวเองหรือของคนอื่น ให้บอกสุภาพว่าต้องเข้าสู่ระบบด้วย YRU Passport ก่อน"
)
ANONYMOUS_PRIVACY_EXAMPLE = (
    "ผู้ใช้: ผมยังขาดกิจกรรมหมวดไหน\n"
    "AURA: ตอนนี้คุณยังไม่ได้เข้าสู่ระบบครับ รบกวนเข้าสู่ระบบด้วย YRU Passport ก่อน"
    " ระหว่างนี้ถ้าอยากดูกิจกรรมที่เปิดรับสมัคร บอกผมได้เลยครับ"
)

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
    """เติมค่าลง prompt ใหม่ทุกครั้งที่เรียก LLM (ไม่เก็บลง messages) · ทุกบทบาทใช้ prompt เดียวกัน"""
    return (template or load_template()).format(
        today=f"{thai_date(today)} ({today.isoformat()})",
        student_name=student.name if student else UNKNOWN_NAME,
        student_faculty=(student.faculty if student else None) or UNKNOWN_FIELD,
        student_major=(student.major if student else None) or UNKNOWN_FIELD,
        student_type=_student_type(student),
        progress_text=progress_text or NO_PROGRESS_TEXT,
        **_privacy(student),
    )


def _privacy(student: StudentProfile | None) -> dict[str, str]:
    if student is not None and student.is_anonymous:
        return {
            "privacy_rule": ANONYMOUS_PRIVACY_RULE,
            "privacy_example": ANONYMOUS_PRIVACY_EXAMPLE,
        }
    if student is not None and not student.is_student:
        return {"privacy_rule": STAFF_PRIVACY_RULE, "privacy_example": STAFF_PRIVACY_EXAMPLE}
    return {"privacy_rule": STUDENT_PRIVACY_RULE, "privacy_example": STUDENT_PRIVACY_EXAMPLE}


def _student_type(student: StudentProfile | None) -> str:
    if student is None:
        return UNKNOWN_FIELD
    if student.is_anonymous:
        return ANONYMOUS_TYPE
    if not student.is_student:
        return f"บุคลากร · {student.position}" if student.position else STAFF_TYPE
    return "เทียบโอน" if student.is_transfer else "นักศึกษาปกติ"
