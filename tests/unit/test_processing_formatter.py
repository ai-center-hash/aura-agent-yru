"""test ของ formatter: วันที่ไทย ปี พ.ศ. และข้อความสั้นที่ส่งให้ LLM"""

from datetime import UTC, date, datetime

from aura_agent.processing import (
    EligibleSchedule,
    analyze_gaps,
    filter_eligible,
    format_attended,
    format_hours,
    format_progress,
    format_recommendations,
    format_registrations,
    format_schedules,
    map_registrations,
    recommend,
    thai_date,
    thai_datetime,
    thai_period,
)
from aura_agent.processing.formatter import MAX_ITEMS, MAX_REGISTRATIONS, UNCERTAIN_TAG


def by_id(schedules, schedule_id):
    return next(schedule for schedule in schedules if schedule.id == schedule_id)


# ---- วันที่และตัวเลข ----


def test_thai_date_uses_buddhist_year():
    assert thai_date(date(2026, 6, 20)) == "20 มิ.ย. 2569"
    assert thai_date(date(2026, 1, 1)) == "1 ม.ค. 2569"
    assert thai_date(date(2026, 12, 31)) == "31 ธ.ค. 2569"


def test_thai_date_converts_timezone():
    """23:30 UTC = 06:30 ของวันถัดไปที่กรุงเทพ"""
    assert thai_date(datetime(2026, 6, 20, 23, 30, tzinfo=UTC)) == "21 มิ.ย. 2569"


def test_thai_date_handles_naive_datetime_as_bangkok():
    assert thai_date(datetime(2026, 6, 20, 8, 50)) == "20 มิ.ย. 2569"


def test_thai_date_none():
    assert thai_date(None) == "ไม่ระบุวัน"
    assert thai_datetime(None) == "ไม่ระบุวัน"


def test_thai_datetime(schedules):
    start = by_id(schedules, 101).activity_start_date

    assert thai_datetime(start) == "5 พ.ย. 2569 09:00"


def test_thai_period_same_day(schedules):
    schedule = by_id(schedules, 101)

    assert (
        thai_period(schedule.activity_start_date, schedule.activity_end_date)
        == "5 พ.ย. 2569 09:00-16:00"
    )


def test_thai_period_across_days():
    start = datetime(2026, 2, 14, 8, 30)
    end = datetime(2026, 2, 15, 16, 30)

    assert thai_period(start, end) == "14 ก.พ. 2569 08:30 - 15 ก.พ. 2569 16:30"


def test_thai_period_without_end(schedules):
    schedule = by_id(schedules, 101)

    assert thai_period(schedule.activity_start_date, None) == "5 พ.ย. 2569 09:00"


def test_thai_period_without_start():
    assert thai_period(None, None) == "ไม่ระบุวันจัด"


def test_format_hours():
    assert format_hours(6.0) == "6 ชม."
    assert format_hours(11.5) == "11.5 ชม."
    assert format_hours(0) == "0 ชม."


# ---- ความคืบหน้า ----


def test_format_progress(summary):
    text = format_progress(analyze_gaps(summary))
    lines = text.splitlines()

    assert lines[0].startswith("[ความคืบหน้า] กรอบ: กรอบกิจกรรมพัฒนานักศึกษา")
    assert "สถานะรวม: ยังไม่ครบ" in lines[0]
    assert "รวม 5 กิจกรรม 27.5 ชม." in lines[0]

    assert "[ผ่านแล้ว]" in text
    assert "[ยังขาด]" in text
    assert "- กิจกรรมจิตอาสาและบำเพ็ญประโยชน์ (บังคับ): ขาด 2 กิจกรรม / 8 ชม." in lines
    assert "- กิจกรรมส่งเสริมสุขภาพและกีฬา (เลือก): ขาด 2 กิจกรรม / 6 ชม." in lines
    assert "- กิจกรรมส่งเสริมทักษะวิชาการและวิชาชีพ (เลือก): 2 กิจกรรม 17.5 ชม." in lines


def test_format_progress_when_complete(load_fixture):
    from aura_agent.data.schemas import StudentSummary

    data = load_fixture("summary_me.json")["data"]
    data["summary"]["overall_status"] = "passed"
    for category in data["categories"]:
        for item in category["frame_items"]:
            item["count"] = 99
            item["total_hours"] = 99.0

    text = format_progress(analyze_gaps(StudentSummary.model_validate(data)))

    assert "สถานะรวม: ครบตามเกณฑ์แล้ว" in text
    assert "[ยังขาด] ครบตามเกณฑ์ทุกหมวดแล้ว" in text


def test_format_progress_without_passed_items(load_fixture):
    from aura_agent.data.schemas import StudentSummary

    data = load_fixture("summary_me.json")["data"]
    data["summary"]["overall_status"] = None
    for category in data["categories"]:
        for item in category["frame_items"]:
            item["count"] = 0
            item["total_hours"] = 0

    text = format_progress(analyze_gaps(StudentSummary.model_validate(data)))

    assert "[ผ่านแล้ว] ยังไม่มีหมวดที่ผ่านเกณฑ์" in text
    assert "สถานะรวม: ยังไม่ครบ" in text  # ไม่มี overall_status ให้เดาจากหมวดที่ขาด


# ---- รายการกิจกรรม ----


def test_format_schedules(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    text = format_schedules(eligible)
    lines = text.splitlines()

    assert lines[0] == "[กิจกรรมที่สมัครได้] 5 รายการ"
    assert lines[1] == (
        "1. จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2 "
        "| หมวด: กิจกรรมจิตอาสาและบำเพ็ญประโยชน์ (บังคับ) "
        "| 5 พ.ย. 2569 09:00-16:00 | 6 ชม. | ว่าง 40/100 | ปิดรับสมัคร 1 พ.ย. 2569"
    )


def test_format_schedules_marks_uncertain_eligibility(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    text = format_schedules(eligible)

    uncertain_lines = [line for line in text.splitlines() if UNCERTAIN_TAG in line]
    assert len(uncertain_lines) == 1
    assert "จิตอาสาซ่อมแซมอุปกรณ์การเรียน" in uncertain_lines[0]


def test_format_schedules_shows_opening_date_for_upcoming_round(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)
    upcoming = [item for item in eligible if item.schedule.id == 103]

    text = format_schedules(upcoming)

    # เทียบรวมตัวคั่นเพราะคำว่า "เปิดรับสมัคร" มีคำว่า "ปิดรับสมัคร" ซ้อนอยู่
    assert "| เปิดรับสมัคร 15 พ.ย. 2569" in text
    assert "| ปิดรับสมัคร" not in text


def test_format_schedules_truncates_at_ten(schedules):
    many = [
        EligibleSchedule(by_id(schedules, 101).model_copy(update={"id": index}))
        for index in range(1, 13)
    ]

    text = format_schedules(many)
    lines = text.splitlines()

    assert lines[0] == f"[กิจกรรมที่สมัครได้] (แสดง {MAX_ITEMS} จาก 12 รายการ)"
    assert len(lines) == MAX_ITEMS + 1
    assert lines[-1].startswith("10. ")


def test_format_schedules_uses_total_when_given(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    text = format_schedules(eligible, total=37)

    assert text.splitlines()[0] == "[กิจกรรมที่สมัครได้] (แสดง 5 จาก 37 รายการ)"


def test_format_schedules_empty():
    assert format_schedules([]) == "[กิจกรรมที่สมัครได้] ไม่มีรายการที่ตรงเงื่อนไข"


def test_format_schedules_without_optional_fields(schedules):
    bare = EligibleSchedule(
        by_id(schedules, 101).model_copy(
            update={
                "activity": None,
                "category_label": None,
                "type_label": None,
                "duration_hours": None,
                "available_slots": None,
                "registration_start_date": None,
                "registration_end_date": None,
                "is_registration_open": True,
            }
        )
    )

    line = format_schedules([bare]).splitlines()[1]

    assert line.startswith("1. (ไม่ทราบชื่อกิจกรรม) | หมวด: ไม่ระบุหมวด")
    assert "ชม." not in line
    assert "ว่าง" not in line
    assert "ไม่ระบุช่วงรับสมัคร" in line


def test_format_schedules_without_max_participants(schedules):
    schedule = EligibleSchedule(by_id(schedules, 101).model_copy(update={"max_participants": None}))

    assert "ว่าง 40 ที่" in format_schedules([schedule])


# ---- กิจกรรมที่แนะนำ ----


def test_format_recommendations(summary, schedules, student, today):
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    text = format_recommendations(recommend(gaps, eligible, limit=10))
    lines = text.splitlines()

    assert lines[0] == "[กิจกรรมที่แนะนำ] 4 รายการ"
    assert lines[1].startswith("1. จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2")
    # หมวดของรอบตรงกับหมวดที่ขาด จึงไม่พูดชื่อหมวดซ้ำ
    assert lines[1].endswith("| ช่วยปิดช่องว่างได้ 6 ชม.")
    assert UNCERTAIN_TAG in lines[2]  # รอบ 108 ที่จำกัดรุ่นปี


def test_format_recommendations_names_gap_when_labels_differ(schedules):
    from aura_agent.processing import Gap

    gap = Gap(
        category_id=2,
        category_name="หมวดจิตอาสา (ชื่อจากกรอบกิจกรรม)",
        type_name="กิจกรรมบังคับ",
        missing_activities=2,
        missing_hours=8.0,
    )
    eligible = [EligibleSchedule(by_id(schedules, 101))]

    text = format_recommendations(recommend([gap], eligible))

    assert "ช่วยปิดหมวด หมวดจิตอาสา (ชื่อจากกรอบกิจกรรม) (บังคับ) ได้ 6 ชม." in text


def test_format_recommendations_empty():
    assert format_recommendations([]) == "[กิจกรรมที่แนะนำ] ไม่มีรายการ"


# ---- ประวัติการลงทะเบียน ----


def test_format_registrations(registrations):
    text = format_registrations(map_registrations(registrations))
    lines = text.splitlines()

    assert lines[0] == "[ประวัติการลงทะเบียน] 6 รายการ"
    assert lines[1] == (
        "1. จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2 | สถานะ: ลงทะเบียนแล้ว | วันจัด 5 พ.ย. 2569 | ยังไม่เช็คอิน"
    )
    assert lines[2] == (
        "2. อบรมปฐมพยาบาลเบื้องต้น | สถานะ: เช็คอินแล้ว | วันจัด 15 ต.ค. 2569 "
        "| เช็คอิน 15 ต.ค. 2569 09:02 | ยังไม่เช็คเอาท์"
    )
    assert "นับได้ 11.5 ชม." in lines[3]

    cancelled = next(line for line in lines if "ยกเลิก" in line)
    assert "เช็คอิน" not in cancelled


def test_format_registrations_filtered(registrations):
    text = format_registrations(map_registrations(registrations, "completed"))

    assert text.splitlines()[0] == "[ประวัติการลงทะเบียน] 3 รายการ"


def test_format_registrations_empty():
    assert format_registrations([]) == "[ประวัติการลงทะเบียน] ไม่มีรายการ"


def test_format_registrations_shows_a_full_history(registrations):
    """นักศึกษาจริงมีประวัติ ~40 รายการ ต้องแสดงครบ (เดิมตัดที่ 10 แล้วบอทตอบว่า "ไม่พบ")"""
    views = map_registrations(registrations) * 7  # 42 รายการ

    lines = format_registrations(views).splitlines()

    assert lines[0] == "[ประวัติการลงทะเบียน] 42 รายการ"
    assert len(lines) == 43


def test_format_registrations_truncates_very_long_history(registrations):
    views = map_registrations(registrations) * 11  # 66 รายการ

    lines = format_registrations(views).splitlines()

    assert lines[0] == f"[ประวัติการลงทะเบียน] (แสดง {MAX_REGISTRATIONS} จาก 66 รายการ)"


def test_short_type_keeps_label_without_prefix(schedules):
    """ป้ายประเภทที่ไม่ได้ขึ้นต้นด้วยคำว่า "กิจกรรม" ให้แสดงตามเดิม"""
    schedule = EligibleSchedule(by_id(schedules, 101).model_copy(update={"type_label": "บังคับ"}))

    assert "หมวด: กิจกรรมจิตอาสาและบำเพ็ญประโยชน์ (บังคับ)" in format_schedules([schedule])


def test_format_no_frame_explains_the_situation():
    from aura_agent.processing import format_no_frame

    text = format_no_frame("ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้")
    lines = text.splitlines()

    assert lines[0].startswith("[ความคืบหน้า] ยังไม่มีกรอบกิจกรรม")
    assert "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้" in lines[0]
    assert "กองพัฒนานักศึกษา" in text
    assert "ค้นหากิจกรรมยังใช้ได้" in text


def test_format_no_frame_without_api_message():
    from aura_agent.processing import format_no_frame

    assert "ระบบกิจกรรมแจ้งว่า" not in format_no_frame(None)


# ---- กิจกรรมที่นับแล้วในแต่ละหมวด (format_attended) ----


def test_attended_lists_activities_per_category(summary):
    text = format_attended(summary)

    assert text.splitlines()[0] == "[กิจกรรมที่นับแล้วในแต่ละหมวด]"
    assert "- กิจกรรมจิตอาสาและบำเพ็ญประโยชน์: นับแล้ว 1 กิจกรรม" in text
    assert "  • จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย | " in text


def test_attended_filters_by_category_keyword(summary):
    text = format_attended(summary, category=" จิตอาสา ")

    assert '[กิจกรรมที่นับแล้วในแต่ละหมวด · หมวดที่มีคำว่า "จิตอาสา"]' in text
    assert "คุณธรรม" not in text


def test_attended_unknown_category_lists_real_names(summary):
    text = format_attended(summary, category="ดนตรี")

    assert 'ไม่มีหมวดที่ชื่อมีคำว่า "ดนตรี"' in text
    assert "กิจกรรมจิตอาสาและบำเพ็ญประโยชน์" in text


def test_attended_finds_titles_without_category_words():
    """ของจริง: กิจกรรมที่นับเป็นจิตอาสาไม่มีคำว่า "จิตอาสา" ในชื่อ (เจอ 2026-10-26)"""
    from tests.evals.personas import load_persona

    summary = load_persona("realistic_with_gaps").summary

    text = format_attended(summary, category="จิตอาสา")

    assert "กิจกรรมสมมติ หมวด 24 ครั้งที่ 1" in text
    assert "กิจกรรมสมมติ หมวด 42 ครั้งที่ 1" in text
