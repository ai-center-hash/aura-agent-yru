"""test กับ persona ที่โครงสร้างเหมือนข้อมูลจริง (`realistic_with_gaps`)

กติกากรอบ (ชื่อหมวด ประเภท เกณฑ์) มาจากกรอบจริง "ปีการศึกษา 2566" ส่วนตัวนักศึกษาและตัวเลขเป็นค่าสมมติ
มีไว้จับปัญหาที่ fixture ตามคู่มือซ่อนไว้ เช่น ประเภทจริงไม่มีคำว่า "บังคับ" (บั๊กที่เจอ 2026-10-21)
"""

from dataclasses import replace

import pytest

from aura_agent.processing import (
    StudentProfile,
    analyze_gaps,
    filter_eligible,
    format_progress,
    format_recommendations,
    format_registrations,
    map_registrations,
    recommend,
)
from tests.evals.personas import EVAL_TODAY, load_persona

MANDATORY_CATEGORY = 1  # หมวด "กิจกรรมบังคับ" ประเภท "กิจกรรมมหาวิทยาลัย"
CLUB_CATEGORY = 111  # ชมรมนักศึกษา: เกณฑ์ 2 กิจกรรม / 0 ชั่วโมง


@pytest.fixture(scope="module")
def persona():
    return load_persona("realistic_with_gaps")


@pytest.fixture(scope="module")
def student(persona) -> StudentProfile:
    return StudentProfile.from_user(persona.summary.user)


@pytest.fixture(scope="module")
def report(persona):
    return analyze_gaps(persona.summary)


def test_frame_has_the_real_structure(persona):
    types = {category.type_name for category in persona.summary.categories}

    assert len(persona.summary.categories) == 14
    assert types == {"กิจกรรมมหาวิทยาลัย", "กิจกรรมเพื่อเสริมสร้างสมรรถนะทั่วไป"}
    assert all("บังคับ" not in name for name in types)  # ต้นเหตุของบั๊ก


def test_mandatory_category_is_detected_from_its_name(report):
    mandatory = [gap.category_id for gap in report.gaps if gap.is_mandatory]

    assert mandatory == [MANDATORY_CATEGORY]
    assert report.gaps[0].category_id == MANDATORY_CATEGORY  # หมวดบังคับขึ้นก่อน


def test_gaps_follow_real_requirements(report):
    gaps = {gap.category_id: gap for gap in report.gaps}

    assert set(gaps) == {1, 111, 20, 21, 5}
    assert (gaps[1].missing_activities, gaps[1].missing_hours) == (3, 12.0)  # เกณฑ์จริง 9/30


def test_zero_hour_requirement_only_counts_activities(report):
    club = next(gap for gap in report.gaps if gap.category_id == CLUB_CATEGORY)

    assert club.missing_activities == 1
    assert club.missing_hours == 0


def test_transfer_students_skip_categories_with_zero_requirement(persona):
    """เกณฑ์เทียบโอนของจิตอาสาปี 3 คือ 0/0 จึงไม่ใช่หมวดที่ขาดสำหรับนักศึกษาเทียบโอน"""
    user = persona.summary.user.model_copy(update={"student_status": "transfer"})
    summary = persona.summary.model_copy(update={"user": user})

    gap_ids = {gap.category_id for gap in analyze_gaps(summary).gaps}

    assert 21 not in gap_ids
    assert 1 in gap_ids  # หมวดบังคับเกณฑ์เท่ากันทั้งสองแบบ


def test_progress_labels_read_naturally(report):
    text = format_progress(report)

    assert "(มหาวิทยาลัย)" not in text  # บั๊กเดิม: ตัดคำ "กิจกรรม" ออกจากชื่อประเภท
    assert "- กิจกรรมบังคับ · กิจกรรมมหาวิทยาลัย: ขาด 3 กิจกรรม / 12 ชม." in text
    assert "- ชมรมนักศึกษา · กิจกรรมมหาวิทยาลัย: ขาด 1 กิจกรรม" in text.splitlines()
    assert "สถานะรวม: ยังไม่ครบ" in text  # overall_status จริงคือ not_passed


def test_student_code_list_controls_eligibility(persona, student):
    eligible = {
        item.schedule.id: item for item in filter_eligible(persona.schedules, student, EVAL_TODAY)
    }

    assert set(eligible) == {7001, 7003, 7004, 7005, 7007}
    assert 7002 not in eligible  # รหัสเราไม่อยู่ในรายชื่อ
    assert eligible[7007].eligibility_uncertain is True  # จำกัดรุ่นปี (Q4)
    assert eligible[7005].eligibility_uncertain is False  # รายชื่อว่าง = ไม่จำกัดด้วยรหัส


def test_student_not_in_any_list_sees_only_open_rounds(persona, student):
    stranger = replace(student, student_id="406600777")

    eligible = {
        item.schedule.id for item in filter_eligible(persona.schedules, stranger, EVAL_TODAY)
    }

    assert eligible == {7005, 7007}


def test_recommendation_puts_mandatory_first_even_if_later(persona, student, report):
    eligible = filter_eligible(persona.schedules, student, EVAL_TODAY)

    recommendations = recommend(report.gaps, eligible, limit=10)

    assert [item.schedule.id for item in recommendations] == [7001, 7003, 7004]
    assert recommendations[0].gap.is_mandatory is True
    assert recommendations[2].schedule.activity_start_date is None  # รอกำหนดวัน ไว้ท้ายสุด


def test_recommendation_text_with_unknown_date(persona, student, report):
    eligible = filter_eligible(persona.schedules, student, EVAL_TODAY)

    text = format_recommendations(recommend(report.gaps, eligible, limit=10))

    assert "จิตอาสาปลูกต้นไม้ (รอกำหนดวัน)" in text
    assert "ไม่ระบุวันจัด" in text


def test_registrations_with_real_nested_shape(persona):
    text = format_registrations(map_registrations(persona.registrations))

    assert text.splitlines()[0] == "[ประวัติการลงทะเบียน] 3 รายการ"
    assert "วันจัด ไม่ระบุวัน" in text  # schedule จริงบางแถวไม่มีวันจัด
    assert "ยังไม่เช็คเอาท์" in text
