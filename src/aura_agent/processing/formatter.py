"""แปลงผลลัพธ์เป็น**ข้อความสั้นภาษาไทย**ให้ LLM อ่าน

ทำเป็นข้อความไม่ใช่ JSON เพราะสั้นกว่าและ Qwen อ่านแม่นกว่า
วันที่เป็นแบบไทย ปี พ.ศ. เขตเวลา Asia/Bangkok และตัดรายการไม่เกิน 10 รายการ
"""

from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo

from ..data.schemas import Schedule
from .models import (
    MANDATORY_KEYWORD,
    EligibleSchedule,
    Gap,
    PassedItem,
    ProgressReport,
    Recommendation,
    RegistrationView,
    is_mandatory_category,
)
from .registration_mapper import CANCELLED_STATUS

BANGKOK: tzinfo = ZoneInfo("Asia/Bangkok")
BUDDHIST_YEAR_OFFSET = 543
THAI_MONTHS = (
    "ม.ค.",
    "ก.พ.",
    "มี.ค.",
    "เม.ย.",
    "พ.ค.",
    "มิ.ย.",
    "ก.ค.",
    "ส.ค.",
    "ก.ย.",
    "ต.ค.",
    "พ.ย.",
    "ธ.ค.",
)

MAX_ITEMS = 10
UNCERTAIN_TAG = "ไม่แน่ใจเรื่องสิทธิ์สมัคร"
# ประเภทแบบตัวอย่างในคู่มือ ย่อได้โดยไม่เสียความหมาย
SHORT_TYPES = {"กิจกรรมบังคับ": "บังคับ", "กิจกรรมเลือก": "เลือก"}

STATUS_TEXT = {
    "passed": "ครบตามเกณฑ์แล้ว",
    "completed": "ครบตามเกณฑ์แล้ว",
    "in_progress": "ยังไม่ครบ",
    "not_passed": "ยังไม่ครบ",
    "failed": "ไม่ผ่าน",
}


# ---- วันที่และตัวเลข ----


def thai_date(value: date | datetime | None, *, tz: tzinfo = BANGKOK) -> str:
    """`2026-06-20` → `20 มิ.ย. 2569`"""
    if value is None:
        return "ไม่ระบุวัน"
    day = _as_date(value, tz)
    return f"{day.day} {THAI_MONTHS[day.month - 1]} {day.year + BUDDHIST_YEAR_OFFSET}"


def thai_datetime(value: datetime | None, *, tz: tzinfo = BANGKOK) -> str:
    """`2026-06-20T09:00:00+07:00` → `20 มิ.ย. 2569 09:00`"""
    if value is None:
        return "ไม่ระบุวัน"
    moment = _to_tz(value, tz)
    return f"{thai_date(moment, tz=tz)} {moment:%H:%M}"


def thai_period(start: datetime | None, end: datetime | None, *, tz: tzinfo = BANGKOK) -> str:
    """ช่วงเวลาของกิจกรรม วันเดียวกันรวมเป็นบรรทัดเดียว (`20 มิ.ย. 2569 09:00-16:00`)"""
    if start is None:
        return "ไม่ระบุวันจัด"
    start_local = _to_tz(start, tz)
    if end is None:
        return thai_datetime(start_local, tz=tz)
    end_local = _to_tz(end, tz)
    if start_local.date() == end_local.date():
        return f"{thai_date(start_local, tz=tz)} {start_local:%H:%M}-{end_local:%H:%M}"
    return f"{thai_datetime(start_local, tz=tz)} - {thai_datetime(end_local, tz=tz)}"


def format_hours(hours: float) -> str:
    """`6.0` → `6 ชม.` และ `11.5` → `11.5 ชม.`"""
    return f"{_number(hours)} ชม."


# ---- ความคืบหน้า ----


def format_progress(report: ProgressReport) -> str:
    """ข้อความที่ใส่ใน system prompt ทุกครั้ง (ดู prompts/system_prompt.th.md)

    ไม่รับ `tz` เพราะส่วนนี้ไม่มีวันที่
    """
    lines = [
        "[ความคืบหน้า] กรอบ: {frame} | สถานะรวม: {status} | รวม {count} กิจกรรม {hours}".format(
            frame=report.frame_title or "ไม่ระบุ",
            status=_status_text(report),
            count=report.total_activities,
            hours=format_hours(report.total_hours),
        )
    ]

    if report.passed_items:
        lines.append("[ผ่านแล้ว]")
        lines.extend(f"- {_passed_line(item)}" for item in report.passed_items)
    else:
        lines.append("[ผ่านแล้ว] ยังไม่มีหมวดที่ผ่านเกณฑ์")

    if report.gaps:
        lines.append("[ยังขาด]")
        lines.extend(f"- {_gap_line(gap)}" for gap in report.gaps)
    else:
        lines.append("[ยังขาด] ครบตามเกณฑ์ทุกหมวดแล้ว")

    return "\n".join(lines)


def format_no_frame(api_message: str | None = None) -> str:
    """ใช้แทน `format_progress` เมื่อระบบกิจกรรมยังไม่มีกรอบกิจกรรมให้นักศึกษาคนนี้"""
    reason = f" (ระบบกิจกรรมแจ้งว่า: {api_message})" if api_message else ""
    lines = [
        f"[ความคืบหน้า] ยังไม่มีกรอบกิจกรรมสำหรับนักศึกษาคนนี้{reason}",
        "จึงยังไม่รู้ว่าต้องเก็บหมวดไหน กี่ชั่วโมง และดูประวัติการลงทะเบียนไม่ได้",
        "ถ้าถูกถามเรื่องความคืบหน้า ให้บอกตามนี้และแนะนำให้ติดต่อกองพัฒนานักศึกษา ส่วนการค้นหากิจกรรมยังใช้ได้ตามปกติ",
    ]
    return "\n".join(lines)


# ---- รายการกิจกรรม ----


def format_schedules(
    items: list[EligibleSchedule], *, total: int | None = None, tz: tzinfo = BANGKOK
) -> str:
    """รายการกิจกรรมที่สมัครได้ (`total` ใส่เมื่อจำนวนทั้งหมดมากกว่าที่ส่งเข้ามา)"""
    if not items:
        return "[กิจกรรมที่สมัครได้] ไม่มีรายการที่ตรงเงื่อนไข"

    shown = items[:MAX_ITEMS]
    count = total if total is not None else len(items)
    header = _header("กิจกรรมที่สมัครได้", shown_count=len(shown), total_count=count)

    lines = [header]
    for index, item in enumerate(shown, start=1):
        detail = _schedule_detail(item.schedule, tz=tz)
        if item.eligibility_uncertain:
            detail = f"{detail} | {UNCERTAIN_TAG}"
        lines.append(f"{index}. {detail}")
    return "\n".join(lines)


def format_recommendations(recommendations: list[Recommendation], *, tz: tzinfo = BANGKOK) -> str:
    """กิจกรรมที่ช่วยปิดหมวดที่ขาด เรียงตามที่ควรสมัครก่อน"""
    if not recommendations:
        return "[กิจกรรมที่แนะนำ] ไม่มีรายการ"

    shown = recommendations[:MAX_ITEMS]
    header = _header("กิจกรรมที่แนะนำ", shown_count=len(shown), total_count=len(recommendations))

    lines = [header]
    for index, item in enumerate(shown, start=1):
        detail = f"{_schedule_detail(item.schedule, tz=tz)} | {_covers_text(item)}"
        if item.eligibility_uncertain:
            detail = f"{detail} | {UNCERTAIN_TAG}"
        lines.append(f"{index}. {detail}")
    return "\n".join(lines)


# ---- ประวัติการลงทะเบียน ----


def format_registrations(views: list[RegistrationView], *, tz: tzinfo = BANGKOK) -> str:
    if not views:
        return "[ประวัติการลงทะเบียน] ไม่มีรายการ"

    shown = views[:MAX_ITEMS]
    header = _header("ประวัติการลงทะเบียน", shown_count=len(shown), total_count=len(views))

    lines = [header]
    for index, view in enumerate(shown, start=1):
        parts = [
            view.title,
            f"สถานะ: {view.status_label}",
            f"วันจัด {thai_date(view.activity_start_date, tz=tz)}",
        ]
        parts.extend(_attendance_parts(view, tz=tz))
        lines.append(f"{index}. " + " | ".join(parts))
    return "\n".join(lines)


# ---- ภายใน ----


def _header(title: str, *, shown_count: int, total_count: int) -> str:
    if shown_count < total_count:
        return f"[{title}] (แสดง {shown_count} จาก {total_count} รายการ)"
    return f"[{title}] {total_count} รายการ"


def _schedule_detail(schedule: Schedule, *, tz: tzinfo) -> str:
    parts = [
        schedule.activity.title if schedule.activity else "(ไม่ทราบชื่อกิจกรรม)",
        f"หมวด: {_with_type(schedule.category_label, schedule.type_label)}",
        thai_period(schedule.activity_start_date, schedule.activity_end_date, tz=tz),
    ]
    if schedule.duration_hours is not None:
        parts.append(format_hours(schedule.duration_hours))
    seats = _seats(schedule)
    if seats:
        parts.append(seats)
    parts.append(_registration_window(schedule, tz=tz))
    return " | ".join(parts)


def _covers_text(item: Recommendation) -> str:
    """บอกว่าช่วยปิดช่องว่างได้กี่ชั่วโมง และบอกชื่อหมวดซ้ำเฉพาะเมื่อไม่ตรงกับหมวดของรอบนั้น"""
    hours = format_hours(item.covers_hours)
    gap_name = _with_type(item.gap.category_name, item.gap.type_name)
    schedule_name = _with_type(item.schedule.category_label, item.schedule.type_label)
    if gap_name == schedule_name:
        return f"ช่วยปิดช่องว่างได้ {hours}"
    return f"ช่วยปิดหมวด {gap_name} ได้ {hours}"


def _seats(schedule: Schedule) -> str | None:
    if schedule.available_slots is None:
        return None
    if schedule.max_participants:
        return f"ว่าง {schedule.available_slots}/{schedule.max_participants}"
    return f"ว่าง {schedule.available_slots} ที่"


def _registration_window(schedule: Schedule, *, tz: tzinfo) -> str:
    """รอบที่ยังไม่เปิดรับสมัครให้บอกวันเปิด ส่วนรอบที่เปิดอยู่ให้บอกวันปิด"""
    if not schedule.is_registration_open and schedule.registration_start_date is not None:
        return f"เปิดรับสมัคร {thai_date(schedule.registration_start_date, tz=tz)}"
    if schedule.registration_end_date is not None:
        return f"ปิดรับสมัคร {thai_date(schedule.registration_end_date, tz=tz)}"
    return "ไม่ระบุช่วงรับสมัคร"


def _attendance_parts(view: RegistrationView, *, tz: tzinfo) -> list[str]:
    if view.status == CANCELLED_STATUS:
        return []
    if view.checkin_at is None:
        return ["ยังไม่เช็คอิน"]
    parts = [f"เช็คอิน {thai_datetime(view.checkin_at, tz=tz)}"]
    if view.attendance_hours is None:
        parts.append("ยังไม่เช็คเอาท์")
    else:
        parts.append(f"นับได้ {format_hours(view.attendance_hours)}")
    return parts


def _passed_line(item: PassedItem) -> str:
    name = _with_type(item.category_name, item.type_name)
    return f"{name}: {item.count} กิจกรรม {format_hours(item.total_hours)}"


def _gap_line(gap: Gap) -> str:
    name = _with_type(gap.category_name, gap.type_name)
    missing = []
    if gap.missing_activities:
        missing.append(f"{gap.missing_activities} กิจกรรม")
    if gap.missing_hours:
        missing.append(format_hours(gap.missing_hours))
    return f"{name}: ขาด {' / '.join(missing)}"


def _with_type(name: str | None, type_name: str | None) -> str:
    """ชื่อหมวดพร้อมป้ายประเภท

    - หมวดบังคับที่ชื่อยังไม่บอก → ต่อท้าย "(บังคับ)"
    - ประเภทแบบในคู่มือ ("กิจกรรมบังคับ"/"กิจกรรมเลือก") → ย่อเป็น "(บังคับ)"/"(เลือก)"
    - ประเภทอื่น (ของจริง เช่น "กิจกรรมมหาวิทยาลัย") → แสดงเต็มหลัง "·" ไม่ตัดคำ
      เพราะตัดแล้วได้ "(มหาวิทยาลัย)" ซึ่งอ่านเหมือนชื่อสถานที่
    """
    label = name or "ไม่ระบุหมวด"
    if is_mandatory_category(name, type_name) and MANDATORY_KEYWORD not in label:
        return f"{label} (บังคับ)"
    if type_name in SHORT_TYPES:
        short = SHORT_TYPES[type_name]
        return label if short in label else f"{label} ({short})"
    if type_name:
        return f"{label} · {type_name}"
    return label


def _status_text(report: ProgressReport) -> str:
    known = STATUS_TEXT.get((report.overall_status or "").lower())
    if known:
        return known
    return "ครบตามเกณฑ์แล้ว" if report.is_complete else "ยังไม่ครบ"


def _as_date(value: date | datetime, tz: tzinfo) -> date:
    if isinstance(value, datetime):
        return _to_tz(value, tz).date()
    return value


def _to_tz(value: datetime, tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _number(value: float) -> str:
    rounded = round(value, 1)
    return str(int(rounded)) if float(rounded).is_integer() else str(rounded)
