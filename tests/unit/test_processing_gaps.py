"""test ของ analyze_gaps: เลือกเกณฑ์ตามประเภทนักศึกษา และคำนวณส่วนที่ขาด"""

from aura_agent.data.schemas import StudentSummary
from aura_agent.processing import analyze_gaps


def test_normal_student_gaps(summary):
    report = analyze_gaps(summary)

    assert report.frame_title is not None
    assert report.frame_title.startswith("กรอบกิจกรรมพัฒนานักศึกษา")
    assert report.overall_status == "in_progress"
    assert report.total_activities == 5
    assert report.total_hours == 27.5
    assert report.is_complete is False

    # เรียงกิจกรรมบังคับก่อน แล้วค่อยหมวดที่ขาดชั่วโมงมากกว่า
    assert [gap.category_id for gap in report.gaps] == [2, 5]

    volunteer, sport = report.gaps
    assert volunteer.missing_activities == 2  # เกณฑ์ 3 ทำได้ 1
    assert volunteer.missing_hours == 8.0  # เกณฑ์ 12 ทำได้ 4
    assert volunteer.is_mandatory is True

    assert sport.missing_activities == 2
    assert sport.missing_hours == 6.0
    assert sport.is_mandatory is False

    assert [item.category_id for item in report.passed_items] == [1, 7]
    assert [gap.category_id for gap in report.mandatory_gaps] == [2]


def test_transfer_student_uses_transfer_requirements(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    data["user"]["student_status"] = "transfer"

    report = analyze_gaps(StudentSummary.model_validate(data))

    assert [gap.category_id for gap in report.gaps] == [2, 5]
    volunteer, sport = report.gaps
    assert volunteer.missing_activities == 1  # เกณฑ์เทียบโอน 2 ทำได้ 1
    assert volunteer.missing_hours == 2.0  # เกณฑ์เทียบโอน 6 ทำได้ 4
    assert sport.missing_activities == 1
    assert sport.missing_hours == 3.0


def test_no_gaps_when_every_requirement_is_met(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    for category in data["categories"]:
        for item in category["frame_items"]:
            item["count"] = 99
            item["total_hours"] = 99.0

    report = analyze_gaps(StudentSummary.model_validate(data))

    assert report.gaps == []
    assert report.is_complete is True
    assert len(report.passed_items) == 4


def test_extra_hours_never_make_a_negative_gap(summary):
    report = analyze_gaps(summary)

    academic = next(item for item in report.passed_items if item.category_id == 7)
    assert academic.total_hours == 17.5  # เกณฑ์แค่ 3 ชม.
    assert all(gap.missing_hours >= 0 for gap in report.gaps)
    assert all(gap.missing_activities >= 0 for gap in report.gaps)


def test_gap_with_only_missing_hours(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    volunteer = data["categories"][1]["frame_items"][0]
    volunteer["count"] = 3  # ครบจำนวนกิจกรรม
    volunteer["total_hours"] = 10.0  # แต่ยังขาด 2 ชม.

    report = analyze_gaps(StudentSummary.model_validate(data))

    gap = next(gap for gap in report.gaps if gap.category_id == 2)
    assert gap.missing_activities == 0
    assert gap.missing_hours == 2.0


def test_gap_with_only_missing_activities(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    volunteer = data["categories"][1]["frame_items"][0]
    volunteer["count"] = 2
    volunteer["total_hours"] = 20.0  # ชั่วโมงเกินเกณฑ์แล้ว เหลือแต่จำนวนกิจกรรม

    report = analyze_gaps(StudentSummary.model_validate(data))

    gap = next(gap for gap in report.gaps if gap.category_id == 2)
    assert gap.missing_activities == 1
    assert gap.missing_hours == 0


def test_empty_categories(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    data["categories"] = []

    report = analyze_gaps(StudentSummary.model_validate(data))

    assert report.gaps == []
    assert report.passed_items == []
    assert report.is_complete is True


def test_summary_without_frame(load_fixture):
    data = load_fixture("summary_me.json")["data"]
    del data["frame"]

    report = analyze_gaps(StudentSummary.model_validate(data))

    assert report.frame_title is None


def test_missing_requirement_counts_as_passed(load_fixture):
    """frame_item ที่ไม่ส่ง requirement มา ถือว่าเกณฑ์เป็น 0 จึงไม่ใช่หมวดที่ขาด"""
    data = load_fixture("summary_me.json")["data"]
    item = data["categories"][2]["frame_items"][0]
    del item["requirement"]

    report = analyze_gaps(StudentSummary.model_validate(data))

    assert 5 not in [gap.category_id for gap in report.gaps]
    assert 5 in [passed.category_id for passed in report.passed_items]
