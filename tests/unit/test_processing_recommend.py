"""test ของ recommend: จับคู่หมวดที่ขาด เรียงลำดับ และตัดตาม limit"""

from aura_agent.processing import (
    EligibleSchedule,
    Gap,
    analyze_gaps,
    filter_eligible,
    recommend,
)

MANDATORY = "กิจกรรมบังคับ"
OPTIONAL = "กิจกรรมเลือก"


def by_id(schedules, schedule_id):
    return next(schedule for schedule in schedules if schedule.id == schedule_id)


def test_recommend_orders_mandatory_then_nearest(summary, schedules, student, today):
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    recommendations = recommend(gaps, eligible, limit=10)

    # บังคับก่อน (หมวด 2: รอบ 101 วันจัด 5 พ.ย. แล้ว 108 วันจัด 10 ธ.ค.)
    # แล้วค่อยหมวดเลือก (หมวด 5: รอบ 107 วันจัด 28 ต.ค. แล้ว 103 วันจัด 2 ธ.ค.)
    assert [item.schedule.id for item in recommendations] == [101, 108, 107, 103]
    assert [item.gap.category_id for item in recommendations] == [2, 2, 5, 5]
    assert recommendations[0].covers_hours == 6.0
    assert recommendations[2].covers_hours == 3.0


def test_recommend_skips_schedules_without_gap(summary, schedules, student, today):
    """รอบ 106 อยู่หมวด 1 ซึ่งผ่านเกณฑ์แล้ว จึงไม่ควรถูกแนะนำ"""
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    recommendations = recommend(gaps, eligible, limit=10)

    assert 106 not in [item.schedule.id for item in recommendations]


def test_recommend_passes_uncertain_flag(summary, schedules, student, today):
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    recommendations = recommend(gaps, eligible, limit=10)

    flagged = {item.schedule.id for item in recommendations if item.eligibility_uncertain}
    assert flagged == {108}


def test_recommend_without_gaps_returns_empty(schedules, student, today):
    eligible = filter_eligible(schedules, student, today)

    assert recommend([], eligible) == []


def test_recommend_respects_limit(summary, schedules, student, today):
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    assert [item.schedule.id for item in recommend(gaps, eligible, limit=2)] == [101, 108]
    assert recommend(gaps, eligible, limit=0) == []


def test_default_limit_is_five(summary, schedules, student, today):
    gaps = analyze_gaps(summary).gaps
    eligible = filter_eligible(schedules, student, today)

    assert len(recommend(gaps, eligible)) <= 5


def test_covers_hours_is_capped_by_missing_hours(schedules):
    gap = Gap(
        category_id=2,
        category_name="จิตอาสา",
        type_name=MANDATORY,
        missing_activities=1,
        missing_hours=2.0,
    )
    six_hour_round = EligibleSchedule(by_id(schedules, 101))  # 6 ชม.

    recommendations = recommend([gap], [six_hour_round])

    assert recommendations[0].covers_hours == 2.0


def test_covers_hours_without_duration(schedules):
    gap = Gap(2, "จิตอาสา", MANDATORY, 1, 6.0)
    no_duration = EligibleSchedule(
        by_id(schedules, 101).model_copy(update={"duration_hours": None})
    )

    assert recommend([gap], [no_duration])[0].covers_hours == 0.0


def test_gap_with_only_missing_activities_still_uses_duration(schedules):
    gap = Gap(2, "จิตอาสา", MANDATORY, 1, 0.0)
    six_hour_round = EligibleSchedule(by_id(schedules, 101))

    assert recommend([gap], [six_hour_round])[0].covers_hours == 6.0


def test_schedule_without_start_date_goes_last(schedules):
    gap = Gap(2, "จิตอาสา", MANDATORY, 2, 8.0)
    undated = EligibleSchedule(
        by_id(schedules, 108).model_copy(update={"activity_start_date": None})
    )
    dated = EligibleSchedule(by_id(schedules, 101))

    recommendations = recommend([gap], [undated, dated])

    assert [item.schedule.id for item in recommendations] == [101, 108]


def test_optional_gap_comes_after_mandatory_even_if_sooner(schedules):
    mandatory_gap = Gap(2, "จิตอาสา", MANDATORY, 2, 8.0)
    optional_gap = Gap(5, "กีฬา", OPTIONAL, 2, 6.0)
    later_mandatory = EligibleSchedule(by_id(schedules, 108))  # 10 ธ.ค.
    sooner_optional = EligibleSchedule(by_id(schedules, 107))  # 28 ต.ค.

    recommendations = recommend([mandatory_gap, optional_gap], [sooner_optional, later_mandatory])

    assert [item.schedule.id for item in recommendations] == [108, 107]
