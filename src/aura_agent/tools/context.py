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
BAD_DATE_MESSAGE = "รูปแบบวันที่ไม่ถูกต้อง ({value}) ต้องเป็น YYYY-MM-DD เช่น 2026-11-05"


def jwt_from(config: RunnableConfig) -> str:
    """ดึง JWT ของนักศึกษาจาก config (ไม่ log และไม่เก็บไว้ที่ไหน)"""
    configurable: Mapping[str, Any] = config.get("configurable") or {}
    jwt = configurable.get("jwt")
    if not jwt:
        raise ValueError("ไม่พบ jwt ใน config['configurable'] (ผู้เรียก graph ต้องส่งมาด้วย)")
    return str(jwt)


def student_from(state: Mapping[str, Any]) -> StudentProfile | None:
    """ดึงข้อมูลนักศึกษาที่ `load_student` เติมไว้ใน state"""
    student = state.get("student")
    return student if isinstance(student, StudentProfile) else None
