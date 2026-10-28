"""test ของตัวทำความสะอาดคำตอบ (api/cleaner.py) · ตัวอย่างมาจากคำตอบจริงใน eval 2026-10-26"""

import json

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

from aura_agent.api.cleaner import AnswerCleaner, known_dates
from aura_agent.api.sse import StreamTranslator

AGENT_META = {"langgraph_node": "agent"}

TOOL_RESULT = (
    "[กิจกรรมที่สมัครได้] 2 รายการ\n"
    "1. **จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2**\n"
    "   - วันจัด: 5 พ.ย. 2569 09:00-16:00 (6 ชม.)\n"
    "   - ที่นั่งว่าง 40/100 · ปิดรับสมัคร 1 พ.ย. 2569\n"
    "2. **กีฬาสีสัมพันธ์นักศึกษา**\n"
    "   - เปิดรับสมัคร 15 พ.ย. 2569"
)


def clean(text: str, *, dates: str = "", chunk: int | None = None) -> str:
    """ป้อนทั้งก้อน หรือทีละ `chunk` ตัวอักษรเหมือนตอน stream"""
    cleaner = AnswerCleaner()
    if dates:
        cleaner.learn_dates(dates)
    size = chunk or max(len(text), 1)
    parts = [cleaner.feed(text[i : i + size]) for i in range(0, len(text), size)]
    return "".join(parts) + cleaner.flush()


CASES = [
    # bullet แบบ * → -
    ("*   **กิจกรรมบังคับ**: ขาด 3 กิจกรรม", "- **กิจกรรมบังคับ**: ขาด 3 กิจกรรม"),
    ("ได้แก่\n* จิตอาสา\n  * ชั้นปีที่ 2", "ได้แก่\n- จิตอาสา\n  - ชั้นปีที่ 2"),
    # ตัวเอียงถูกตัด ตัวหนาคงไว้
    ("   - *หมายเหตุ: ไม่แน่ใจเรื่องสิทธิ์สมัคร*", "   - หมายเหตุ: ไม่แน่ใจเรื่องสิทธิ์สมัคร"),
    ("**ตัวหนา** กับ *เอียง*", "**ตัวหนา** กับ เอียง"),
    ("***ทั้งคู่***", "**ทั้งคู่**"),
    # คำลงท้าย/สรรพนาม
    ("ส่วนนี้ใช้ได้เฉพาะนักศึกษาค่ะครับ", "ส่วนนี้ใช้ได้เฉพาะนักศึกษาครับ"),
    ("สำหรับนักศึกษาค่ะ\n\nแต่หากคุณต้องการ", "สำหรับนักศึกษาครับ\n\nแต่หากคุณต้องการ"),
    ("อยากให้แนะนำไหมคะ", "อยากให้แนะนำไหมครับ"),
    ("ดิฉันช่วยได้ค่ะ", "ผมช่วยได้ครับ"),
    ("หรือคะแนนสอบ", "หรือคะแนนสอบ"),  # "คะแนน" ไม่ใช่คำลงท้าย
    # emoji
    ("ครบทุกหมวดแล้วครับ 🎉", "ครบทุกหมวดแล้วครับ "),
    ("⚠️ ตรวจเงื่อนไข", " ตรวจเงื่อนไข"),
    # ข้อความปกติไม่เปลี่ยน
    ("1. **ชื่อ**\n   - วันจัด: 5 พ.ย. 2569", "1. **ชื่อ**\n   - วันจัด: 5 พ.ย. 2569"),
]


@pytest.mark.parametrize(("raw", "expected"), CASES)
@pytest.mark.parametrize("chunk", [None, 1, 3, 7])
def test_cleaner_fixes_style_even_when_split(raw, expected, chunk):
    assert clean(raw, chunk=chunk) == expected


@pytest.mark.parametrize("chunk", [None, 1, 2, 5])
def test_cleaner_fixes_month_typo_from_tool_dates(chunk):
    """eval เจอ "ปิดรับสมัคร: 1 พ.ค. 2569" ทั้งที่ผลของเครื่องมือคือ 1 พ.ย. 2569"""
    raw = "   - ปิดรับสมัคร: 1 พ.ค. 2569\nจัดวันที่ 5 พ.ค."

    assert clean(raw, dates=TOOL_RESULT, chunk=chunk) == (
        "   - ปิดรับสมัคร: 1 พ.ย. 2569\nจัดวันที่ 5 พ.ย."
    )


def test_cleaner_keeps_dates_that_exist_in_tool_result():
    raw = "ปิดรับสมัคร 1 พ.ย. 2569 และเปิดรับสมัคร 15 พ.ย. 2569"

    assert clean(raw, dates=TOOL_RESULT) == raw


def test_cleaner_does_not_guess_when_no_close_match():
    # 20 พ.ค. ไม่มีในข้อมูล และ 20 พ.ย. ก็ไม่มี → ไม่แก้ (ไม่เดา)
    assert clean("วันที่ 20 พ.ค. 2569", dates=TOOL_RESULT) == "วันที่ 20 พ.ค. 2569"
    # ไม่มีผลของเครื่องมือเลย → ไม่แตะวันที่
    assert clean("วันที่ 1 พ.ค. 2569") == "วันที่ 1 พ.ค. 2569"


def test_cleaner_does_not_guess_between_two_candidates():
    dates = "1 มี.ค. 2569 และ 1 พ.ค. 2569"  # "1 มิ.ย." ห่างจากทั้งคู่มากกว่า 1 ตัวอักษร
    assert clean("วันที่ 1 มิ.ย. 2569", dates=dates) == "วันที่ 1 มิ.ย. 2569"


@pytest.mark.parametrize("chunk", [None, 1, 3])
def test_cleaner_keeps_dates_the_user_typed(chunk):
    """ผู้ใช้ถามถึง 1 พ.ค. เอง (ปีจะพิมพ์หรือไม่ก็ได้) โมเดลตอบถึงวันนั้น → ห้ามแก้เป็น 1 พ.ย. ที่อยู่ในผลของเครื่องมือ"""
    cleaner = AnswerCleaner()
    cleaner.learn_dates(TOOL_RESULT)
    cleaner.learn_user_dates("วันที่ 1 พ.ค. 69 มีกิจกรรมไหม")
    raw = "วันที่ 1 พ.ค. 2569 ไม่มีกิจกรรมครับ แต่ปิดรับสมัคร 5 พ.ค. 2569"

    size = chunk or len(raw)
    text = "".join(cleaner.feed(raw[i : i + size]) for i in range(0, len(raw), size))

    # 1 พ.ค. ผู้ใช้พิมพ์เอง จึงคงไว้ · 5 พ.ค. ผู้ใช้ไม่ได้พูดถึง จึงยังแก้ตามผลของเครื่องมือ
    assert text + cleaner.flush() == "วันที่ 1 พ.ค. 2569 ไม่มีกิจกรรมครับ แต่ปิดรับสมัคร 5 พ.ย. 2569"


def test_known_dates_with_and_without_year():
    found = known_dates([TOOL_RESULT])

    assert ("1", "พ.ย.", "2569") in found
    assert ("1", "พ.ย.", None) in found
    assert ("15", "พ.ย.", "2569") in found


def test_cleaner_holds_back_only_a_short_tail():
    """ตัวกรองต้องไม่ทำให้ข้อความค้างนาน (กันไว้แค่ท้ายสั้นๆ)"""
    cleaner = AnswerCleaner()
    text = "คุณยังขาดกิจกรรมอีก 2 หมวดครับ ได้แก่ จิตอาสาและกีฬา"

    sent = cleaner.feed(text)

    assert text.startswith(sent)
    assert len(text) - len(sent) <= 16


def _token_text(events) -> str:
    return "".join(json.loads(e["data"])["text"] for e in events if e["event"] == "token")


def test_translator_fixes_dates_using_tool_messages():
    translator = StreamTranslator()
    tool_update = {"tools": {"messages": [ToolMessage(TOOL_RESULT, tool_call_id="1")]}}

    events = [
        *translator.handle("updates", tool_update),
        *translator.handle("messages", (AIMessageChunk(content="ปิดรับสมัคร 1 พ."), AGENT_META)),
        *translator.handle("messages", (AIMessageChunk(content="ค. 2569 ค่ะ"), AGENT_META)),
        *translator.flush(),
    ]

    assert _token_text(events) == "ปิดรับสมัคร 1 พ.ย. 2569 ครับ"
