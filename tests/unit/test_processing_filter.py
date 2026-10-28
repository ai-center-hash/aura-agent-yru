"""test ของ filter_eligible: ตัดรอบที่เต็ม หมดเวลา และกลุ่มเป้าหมายไม่ตรง"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from aura_agent.processing import filter_eligible
from aura_agent.processing import schedule_filter as module


def ids(eligible) -> list[int]:
    return [item.schedule.id for item in eligible]


def test_filter_with_fixture(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    # 88 หมดเวลารับสมัคร · 102 เต็ม · 104 คนละคณะ · 105 เฉพาะเทียบโอน
    assert ids(eligible) == [101, 103, 106, 107, 108]


def test_full_round_is_dropped(schedules, student, today):
    assert 102 not in ids(filter_eligible(schedules, student, today))


def test_expired_registration_is_dropped(schedules, student, today):
    assert 88 not in ids(filter_eligible(schedules, student, today))


def test_last_day_of_registration_is_still_eligible(schedules, student):
    """รอบ 107 ปิดรับสมัคร 2026-10-26 — วันสุดท้ายยังสมัครได้ วันถัดไปต้องหลุด"""
    on_deadline = ids(filter_eligible(schedules, student, date(2026, 10, 26)))
    after_deadline = ids(filter_eligible(schedules, student, date(2026, 10, 27)))

    assert 107 in on_deadline
    assert 107 not in after_deadline


def test_deadline_in_utc_is_compared_in_thai_time(schedules, student):
    """17:30 UTC ของวันที่ 26 = 00:30 ของวันที่ 27 ตามเวลาไทย จึงยังสมัครได้ในวันที่ 27"""
    late_utc = [
        schedule.model_copy(
            update={"registration_end_date": datetime(2026, 10, 26, 17, 30, tzinfo=UTC)}
        )
        for schedule in schedules
        if schedule.id == 107
    ]

    assert ids(filter_eligible(late_utc, student, date(2026, 10, 27))) == [107]
    assert ids(filter_eligible(late_utc, student, date(2026, 10, 28))) == []


def test_other_faculty_is_dropped(schedules, student, today):
    assert 104 not in ids(filter_eligible(schedules, student, today))


def test_transfer_only_round_is_dropped_for_normal_student(schedules, student, today):
    assert 105 not in ids(filter_eligible(schedules, student, today))


def test_transfer_student_gets_the_transfer_round(schedules, student, today):
    transfer_student = replace(student, student_status="transfer")

    eligible = ids(filter_eligible(schedules, transfer_student, today))

    assert 105 in eligible  # รอบเฉพาะเทียบโอน
    assert 108 not in eligible  # รอบเฉพาะนักศึกษาปกติ


def test_student_without_faculty_is_dropped_from_restricted_round(schedules, student, today):
    no_faculty = replace(student, faculty=None)

    assert 108 not in ids(filter_eligible(schedules, no_faculty, today))


def test_year_prefix_round_is_flagged_uncertain(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    flagged = {item.schedule.id for item in eligible if item.eligibility_uncertain}
    assert flagged == {108}

    item = next(item for item in eligible if item.schedule.id == 108)
    assert item.uncertain_reason == module.UNCERTAIN_YEAR_PREFIX


def test_unrestricted_round_is_never_uncertain(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    unrestricted = next(item for item in eligible if item.schedule.id == 101)
    assert unrestricted.eligibility_uncertain is False
    assert unrestricted.uncertain_reason is None


def test_upcoming_round_is_kept(schedules, student, today):
    """รอบที่ยังไม่เปิดรับสมัครต้องไม่ถูกตัด (ใช้ตอบคำถาม "กำลังจะเปิด")"""
    eligible = filter_eligible(schedules, student, today)

    upcoming = next(item for item in eligible if item.schedule.id == 103)
    assert upcoming.schedule.is_registration_open is False


def test_round_without_deadline_is_kept(schedules, student, today):
    without_deadline = [
        schedule.model_copy(update={"registration_end_date": None})
        for schedule in schedules
        if schedule.id == 88
    ]

    assert ids(filter_eligible(without_deadline, student, today)) == [88]


def test_empty_input(student, today):
    assert filter_eligible([], student, today) == []


def test_year_prefix_rule_is_still_open():
    """Q4 ยังไม่มีคำตอบ: ธงต้องเป็น False และฟังก์ชันเทียบรุ่นต้องยังใช้ไม่ได้"""
    assert module.YEAR_PREFIX_RULE_KNOWN is False

    with pytest.raises(NotImplementedError):
        module._matches_year_prefix(None, None)


def test_student_profile_from_summary_user(summary):
    from aura_agent.processing import StudentProfile

    profile = StudentProfile.from_user(summary.user)

    assert profile.id == 119231
    assert profile.student_id == "406510024"
    assert profile.faculty == "คณะวิทยาศาสตร์และเทคโนโลยี"
    assert profile.is_transfer is False
    assert replace(profile, student_status="transfer").is_transfer is True


def test_restricted_round_without_status_target(schedules, student, today):
    """รอบที่จำกัดแค่คณะกับรุ่นปี (ไม่ระบุประเภทนักศึกษา) ต้องผ่านด่าน student_status"""
    open_to_all_statuses = [
        schedule.model_copy(
            update={
                "target_faculties": [student.faculty],
                "target_student_status": None,
            }
        )
        for schedule in schedules
        if schedule.id == 104
    ]

    eligible = filter_eligible(open_to_all_statuses, student, today)

    assert ids(eligible) == [104]
    assert eligible[0].eligibility_uncertain is True  # ยังจำกัดรุ่นปี 67


# ---- รอบที่จำกัดด้วยรายรหัสนักศึกษา (ข้อมูลจริงใช้แบบนี้ 30/32 รอบ) ----


def coded(schedule, *codes):
    return schedule.model_copy(update={"is_restricted": True, "target_student_codes": list(codes)})


def test_student_in_code_list_can_apply(schedules, student, today):
    round_101 = next(s for s in schedules if s.id == 101)

    eligible = filter_eligible([coded(round_101, "406500999", student.student_id)], student, today)

    assert ids(eligible) == [101]
    assert eligible[0].eligibility_uncertain is False


def test_student_not_in_code_list_is_dropped(schedules, student, today):
    round_101 = next(s for s in schedules if s.id == 101)

    assert filter_eligible([coded(round_101, "406500999")], student, today) == []


def test_unknown_student_code_is_flagged_uncertain(schedules, student, today):
    round_101 = next(s for s in schedules if s.id == 101)
    unknown = replace(student, student_id=None)

    eligible = filter_eligible([coded(round_101, "406500999")], unknown, today)

    assert ids(eligible) == [101]
    assert eligible[0].eligibility_uncertain is True
    assert eligible[0].uncertain_reason == module.UNCERTAIN_STUDENT_CODES


def test_code_list_combines_with_other_rules(schedules, student, today):
    """อยู่ในรายชื่อแต่คนละคณะ ก็ยังสมัครไม่ได้"""
    round_104 = next(s for s in schedules if s.id == 104)  # จำกัดคณะครุศาสตร์

    assert filter_eligible([coded(round_104, student.student_id)], student, today) == []


def test_student_profile_from_passport():
    from aura_agent.data.schemas import PassportUser
    from aura_agent.processing import StudentProfile

    profile = StudentProfile.from_passport(
        PassportUser(
            sub="10001",
            username="406500001",
            user_type="student",
            display_name="นักศึกษาทดสอบ ระบบ",
            org_unit_1_name="คณะวิทยาศาสตร์และเทคโนโลยี",
        )
    )

    assert profile.id is None  # ยังไม่มีกรอบกิจกรรม จึงไม่รู้ user_id ของ Activity API
    assert profile.student_id == "406500001"
    assert profile.name == "นักศึกษาทดสอบ ระบบ"
    assert profile.faculty == "คณะวิทยาศาสตร์และเทคโนโลยี"
