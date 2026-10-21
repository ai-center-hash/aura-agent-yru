"""เวลาและวันที่ของแอป

รวมไว้ที่เดียวเพราะ `processing/` ห้ามเรียก `datetime.now()` เอง (รับ `today` เป็น argument)
ชั้นที่อยู่เหนือกว่า (tools, agent, api) เรียกจากที่นี่แล้วส่งค่าลงไป
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import get_settings


def app_timezone() -> ZoneInfo:
    """เขตเวลาตาม `TIMEZONE` ใน .env (ค่าเริ่มต้น Asia/Bangkok)"""
    return ZoneInfo(get_settings().timezone)


def now() -> datetime:
    return datetime.now(app_timezone())


def today() -> date:
    return now().date()
