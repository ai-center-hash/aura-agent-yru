"""test ของ clock — ชั้น processing พึ่งค่าจากที่นี่ จึงต้องแน่ใจว่าเขตเวลาถูก"""

from datetime import date, datetime

from aura_agent import clock


def test_app_timezone_follows_settings(monkeypatch):
    assert str(clock.app_timezone()) == "Asia/Bangkok"


def test_now_is_timezone_aware():
    moment = clock.now()

    assert isinstance(moment, datetime)
    assert moment.tzinfo is not None
    assert moment.utcoffset() is not None
    assert moment.utcoffset().total_seconds() == 7 * 3600


def test_today_matches_bangkok_date():
    assert clock.today() == clock.now().date()
    assert isinstance(clock.today(), date)
