"""คัดรอบกิจกรรมที่นักศึกษาคนนี้สมัครได้

ตัดทิ้งเมื่อ
- รอบเต็ม (`is_full`)
- หมดเวลารับสมัครไปแล้ว (`registration_end_date` < วันนี้)
- จำกัดกลุ่มเป้าหมายและคุณสมบัติไม่ตรง (รายรหัส / คณะ / ประเภทนักศึกษา / รหัสปีที่เข้า)

รหัสปีที่เข้า (`target_student_year_prefix` เช่น "66") เทียบกับหลักที่ 3–4 ของรหัสนักศึกษา
(รหัส มรย. รูปแบบ 40**66**xxxxx · Q4 ยืนยันโดยผู้ใช้ 2026-11-10) · ไม่รู้รหัสของผู้ใช้ → ปล่อยผ่าน
"""

from datetime import date

from ..data.schemas import Schedule
from .formatter import BANGKOK
from .models import EligibleSchedule, StudentProfile

# ตำแหน่งของปีที่เข้าในรหัสนักศึกษา: "406600101"[2:4] = "66"
ENTRY_YEAR_SLICE = slice(2, 4)

UNCERTAIN_YEAR_PREFIX = "จำกัดรหัสปีที่เข้า แต่ไม่ทราบรหัสของผู้ใช้"
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
        if not _matches_year_prefix(schedule, student):
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


def filter_for_cohort(items: list[EligibleSchedule], cohort: str) -> list[EligibleSchedule]:
    """ตัดรอบที่จำกัดรหัสปีที่เข้าไว้ให้รุ่นอื่น (ใช้กับผลของ `filter_open` เมื่อบุคลากรถามตามรุ่นรหัส)

    รอบที่จำกัดด้วยเงื่อนไขอื่น (คณะ/รายชื่อ/ประเภท) ยังอยู่ formatter จะติดป้ายกลุ่มให้
    """
    year = cohort.strip()[-2:]
    kept = []
    for item in items:
        targets = {str(v).strip()[-2:] for v in item.schedule.target_student_year_prefix}
        if not targets or year in targets:
            kept.append(item)
    return kept


def _registration_closed(schedule: Schedule, today: date) -> bool:
    """ปิดรับสมัครแล้วหรือยัง (วันสุดท้ายยังนับว่าสมัครได้)

    เทียบเป็นวันตามเวลาไทยเหมือน formatter เผื่อ API ส่งเวลาแบบ UTC มา
    (`2026-10-26T17:30:00Z` คือ 27 ต.ค. ตามเวลาไทย ไม่ใช่ 26)
    """
    deadline = schedule.registration_end_date
    if deadline is None:
        return False
    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(BANGKOK)
    return deadline.date() < today


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
    if schedule.target_student_year_prefix and entry_year(student) is None:
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


def entry_year(student: StudentProfile) -> str | None:
    """ปีที่เข้า 2 หลักจากรหัสนักศึกษา (มาจาก token ไม่ใช่จากข้อความ) · ไม่รู้ → None"""
    code = (student.student_id or "").strip()
    year = code[ENTRY_YEAR_SLICE]
    if len(code) < ENTRY_YEAR_SLICE.stop or not year.isdigit():
        return None
    return year


def _matches_year_prefix(schedule: Schedule, student: StudentProfile) -> bool:
    """รอบที่จำกัดรหัสปีที่เข้า สมัครได้เฉพาะนักศึกษาที่รหัสหลักที่ 3–4 ตรง

    ค่าใน API เป็น 2 หลัก ("66") ถ้าวันหลังมาเป็น พ.ศ. 4 หลัก ("2566") ใช้ 2 หลักท้าย
    """
    targets = {str(value).strip()[-2:] for value in schedule.target_student_year_prefix}
    if not targets:
        return True
    year = entry_year(student)
    return year is None or year in targets
