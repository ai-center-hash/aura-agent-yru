"""test ของ registration_mapper: สถานะเป็นภาษาไทย กรองตามสถานะ และนาที → ชั่วโมง"""

import pytest

from aura_agent.processing import attendance_hours, map_registrations, status_label


def test_map_all_registrations(registrations):
    views = map_registrations(registrations)

    assert len(views) == 6
    assert [view.status_label for view in views] == [
        "ลงทะเบียนแล้ว",
        "เช็คอินแล้ว",
        "เข้าร่วมสมบูรณ์",
        "เข้าร่วมสมบูรณ์",
        "ยกเลิก",
        "เข้าร่วมสมบูรณ์",
    ]

    pending = views[0]
    assert pending.title.startswith("จิตอาสา")
    assert pending.checkin_at is None
    assert pending.attendance_hours is None
    assert pending.activity_start_date is not None
    assert pending.activity_start_date.year == 2026

    checked_in = views[1]
    assert checked_in.checkin_at is not None
    assert checked_in.attendance_hours is None  # ยังไม่เช็คเอาท์

    assert views[2].attendance_hours == 11.5  # 690 นาที
    assert views[3].attendance_hours == 6.0  # 360 นาที
    assert views[5].attendance_hours == 3.0  # 180 นาที


@pytest.mark.parametrize(
    ("status_filter", "expected"),
    [
        ("registered", [1]),
        ("checked_in", [4]),
        ("completed", [5, 5, 5]),
        ("cancelled", [6]),
    ],
)
def test_filter_by_status(registrations, status_filter, expected):
    views = map_registrations(registrations, status_filter)

    assert [view.status for view in views] == expected


def test_no_filter_keeps_api_order(registrations):
    views = map_registrations(registrations, None)

    assert [view.status for view in views] == [1, 4, 5, 5, 6, 5]


def test_unknown_filter_is_ignored(registrations):
    """ค่า status มาจาก LLM ซึ่งพิมพ์ผิดได้ ถ้าไม่รู้จักให้คืนทุกรายการแทนที่จะคืนว่าง"""
    views = map_registrations(registrations, "ลงทะเบียน")  # type: ignore[arg-type]

    assert len(views) == 6


def test_unknown_status_code_gets_readable_label():
    assert status_label(2) == "สถานะอื่น (2)"
    assert status_label(5) == "เข้าร่วมสมบูรณ์"


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(None, None), (0, 0.0), (90, 1.5), (100, 1.7), (690, 11.5)],
)
def test_attendance_hours(minutes, expected):
    assert attendance_hours(minutes) == expected


def test_registration_without_activity_or_schedule(registrations):
    row = registrations[0].model_copy(update={"activity": None, "schedule": None})

    view = map_registrations([row])[0]

    assert view.title == "(ไม่ทราบชื่อกิจกรรม)"
    assert view.activity_start_date is None


def test_empty_input():
    assert map_registrations([]) == []
