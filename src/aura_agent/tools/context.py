"""ตัวช่วยที่ tool ทุกตัวใช้ร่วมกัน: ดึง JWT จาก config และดึงนักศึกษาจาก state

**กฎความปลอดภัย:** JWT อยู่ใน `config["configurable"]["jwt"]` เท่านั้น (ไม่อยู่ใน state ที่ถูกบันทึกลง SQLite)
และ `user_id` มาจาก `state["student"]` ซึ่ง `load_student` เติมจาก `summary/me` เท่านั้น
tool จึงไม่มี parameter สำหรับรหัสนักศึกษาหรือ user_id ให้ LLM กรอกได้เลย
"""

from collections.abc import Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig

from ..processing import StudentProfile

NO_STUDENT_MESSAGE = "ตอนนี้ผมยังไม่มีข้อมูลนักศึกษาของคุณครับ รบกวนลองถามใหม่อีกครั้ง ถ้ายังไม่ได้ให้ติดต่อกองพัฒนานักศึกษา"
NOT_STUDENT_MESSAGE = (
    "ผู้ใช้คนนี้เป็นบุคลากร ไม่ใช่นักศึกษา จึงไม่มี{subject}ของตัวเอง"
    " ให้บอกสุภาพว่าส่วนนี้ใช้ได้เฉพาะนักศึกษา และบุคลากรก็ดูข้อมูลของนักศึกษาคนอื่นไม่ได้"
    " ถ้าอยากดูรอบกิจกรรมที่ยังรับสมัคร ให้ใช้การค้นหากิจกรรม"
)
LOGIN_REQUIRED_MESSAGE = (
    "ผู้ใช้ยังไม่ได้เข้าสู่ระบบ จึงไม่รู้ว่าเป็นใครและดูข้อมูลส่วนตัวไม่ได้"
    " ให้บอกสุภาพว่าต้องเข้าสู่ระบบด้วย YRU Passport ก่อน ส่วนการค้นหารอบกิจกรรมใช้ได้เลย"
)
BAD_DATE_MESSAGE = "รูปแบบวันที่ไม่ถูกต้อง ({value}) ต้องเป็น YYYY-MM-DD เช่น 2026-11-05"


def jwt_from(config: RunnableConfig) -> str:
    """ดึง JWT ของผู้ใช้จาก config (ไม่ log และไม่เก็บไว้ที่ไหน)

    ผู้ใช้ที่ไม่ได้เข้าสู่ระบบไม่มี JWT · tool ที่ต้องใช้ข้อมูลส่วนตัวต้องเช็ค `personal_data_refusal` ก่อนเรียก
    """
    jwt = optional_jwt_from(config)
    if not jwt:
        raise ValueError("ไม่พบ jwt ใน config['configurable'] (ผู้ใช้ไม่ได้เข้าสู่ระบบ)")
    return jwt


def optional_jwt_from(config: RunnableConfig) -> str | None:
    """JWT ถ้ามี (ใช้กับข้อมูลสาธารณะ เช่น รอบกิจกรรม ที่ผู้ใช้ทั่วไปก็ดูได้)"""
    configurable: Mapping[str, Any] = config.get("configurable") or {}
    jwt = configurable.get("jwt")
    return str(jwt) if jwt else None


def personal_data_refusal(student: StudentProfile | None, subject: str) -> str | None:
    """ข้อความปฏิเสธถ้าผู้ใช้คนนี้ไม่มีข้อมูลกิจกรรมของตัวเอง (None = ใช้ได้)"""
    if student is None:
        return NO_STUDENT_MESSAGE
    if student.is_anonymous:
        return LOGIN_REQUIRED_MESSAGE
    if not student.is_student:
        return NOT_STUDENT_MESSAGE.format(subject=subject)
    return None


def student_from(state: Mapping[str, Any]) -> StudentProfile | None:
    """ดึงข้อมูลนักศึกษาที่ `load_student` เติมไว้ใน state"""
    student = state.get("student")
    return student if isinstance(student, StudentProfile) else None
