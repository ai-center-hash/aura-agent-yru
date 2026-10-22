"""คัดรอบกิจกรรมที่นักศึกษาคนนี้สมัครได้

ตัดทิ้งเมื่อ
- รอบเต็ม (`is_full`)
- หมดเวลารับสมัครไปแล้ว (`registration_end_date` < วันนี้)
- จำกัดกลุ่มเป้าหมายและคุณสมบัติไม่ตรง (คณะ / ประเภทนักศึกษา)

เงื่อนไข "รุ่นปี" (`target_student_year_prefix`) ยังเทียบไม่ได้เพราะ **Q4 ยังไม่มีคำตอบ**
ว่าค่านี้เทียบกับปีที่เข้าศึกษาหรือสองตัวแรกของรหัสนักศึกษา จึงปล่อยผ่านไว้ก่อน
แล้วติดป้าย `eligibility_uncertain` ให้ผู้ใช้ไปตรวจเงื่อนไขในระบบกิจกรรมเองก่อนสมัคร
"""

from datetime import date

from ..data.schemas import Schedule
from .models import EligibleSchedule, StudentProfile

# เปลี่ยนเป็น True เมื่อ Q4 มีคำตอบแล้ว และเติมวิธีเทียบใน `_matches_year_prefix`
YEAR_PREFIX_RULE_KNOWN = False

UNCERTAIN_YEAR_PREFIX = "จำกัดรุ่นปี"
UNCERTAIN_STUDENT_CODES = "จำกัดรายชื่อนักศึกษา แต่ไม่ทราบรหัสของผู้ใช้"


def filter_eligible(
    schedules: list[Schedule], student: StudentProfile, today: date
) -> list[EligibleSchedule]:
    """คืนเฉพาะรอบที่สมัครได้ โดยคงลำดับเดิมที่ API ส่งมา"""
    eligible: list[EligibleSchedule] = []

    for schedule in schedules:
        if schedule.is_full:
            continue
        if _registration_closed(schedule, today):
            continue
        if not schedule.is_restricted:
            eligible.append(EligibleSchedule(schedule))
            continue
        if not _matches_student_code(schedule, student):
            continue
        if not _matches_faculty(schedule, student):
            continue
        if not _matches_student_status(schedule, student):
            continue

        reason = _uncertain_reason(schedule, student)
        eligible.append(
            EligibleSchedule(
                schedule, eligibility_uncertain=reason is not None, uncertain_reason=reason
            )
        )

    return eligible


def filter_open(schedules: list[Schedule], today: date) -> list[EligibleSchedule]:
    """รอบที่ยังรับสมัครได้ทั้งหมด ไม่ดูคุณสมบัติผู้สมัคร (ใช้กับบุคลากรที่ไม่ได้สมัครเอง)

    ตัดแค่รอบที่เต็มและรอบที่หมดเวลารับสมัคร รอบที่จำกัดกลุ่มเป้าหมายยังแสดง
    แต่ formatter จะติดป้ายว่าเปิดเฉพาะบางกลุ่ม
    """
    return [
        EligibleSchedule(schedule)
        for schedule in schedules
        if not schedule.is_full and not _registration_closed(schedule, today)
    ]


def _registration_closed(schedule: Schedule, today: date) -> bool:
    """ปิดรับสมัครแล้วหรือยัง (วันสุดท้ายยังนับว่าสมัครได้)"""
    deadline = schedule.registration_end_date
    return deadline is not None and deadline.date() < today


def _matches_student_code(schedule: Schedule, student: StudentProfile) -> bool:
    """รอบที่ระบุรายรหัสนักศึกษาไว้ สมัครได้เฉพาะคนที่อยู่ในรายชื่อ

    ข้อมูลจริง 30/32 รอบจำกัดสิทธิ์ด้วยวิธีนี้ (ความหมายแน่ชัดรอผล Q7 ใน HANDOFF)
    ถ้าไม่รู้รหัสของผู้ใช้ ให้ผ่านไปก่อนแล้วติดป้ายไม่แน่ใจ (ดู `_uncertain_reason`)
    """
    if not schedule.target_student_codes or not student.student_id:
        return True
    return student.student_id in schedule.target_student_codes


def _uncertain_reason(schedule: Schedule, student: StudentProfile) -> str | None:
    if schedule.target_student_codes and not student.student_id:
        return UNCERTAIN_STUDENT_CODES
    if schedule.target_student_year_prefix and not YEAR_PREFIX_RULE_KNOWN:
        return UNCERTAIN_YEAR_PREFIX
    return None


def _matches_faculty(schedule: Schedule, student: StudentProfile) -> bool:
    if not schedule.target_faculties:
        return True
    return student.faculty in schedule.target_faculties


def _matches_student_status(schedule: Schedule, student: StudentProfile) -> bool:
    target = schedule.target_student_status
    if not target:
        return True
    return target == student.student_status


def _matches_year_prefix(schedule: Schedule, student: StudentProfile) -> bool:
    """ยังใช้ไม่ได้จนกว่า Q4 จะมีคำตอบ (ดู `YEAR_PREFIX_RULE_KNOWN`)

    เมื่อรู้แล้วให้เทียบ `schedule.target_student_year_prefix` กับฟิลด์ที่ถูกต้องของนักศึกษา
    """
    raise NotImplementedError("รอผล Q4 ว่า target_student_year_prefix เทียบกับฟิลด์ไหน")
