"""ทำความสะอาดคำตอบของโมเดลระหว่าง stream ก่อนส่งถึงผู้ใช้

แก้ด้วยโค้ดแทนการเพิ่มกฎใน prompt เพราะ qwen3.6 ไวต่อถ้อยคำของ prompt มาก
(เพิ่มกฎรูปแบบทีไร ข้ออื่นใน eval ตกสลับกัน · HANDOFF 2026-10-26) · ทำแบบนี้ได้ผลแน่นอนทุกคำตอบ

| อาการที่เจอใน eval | แก้เป็น |
|---|---|
| bullet `* ` / `*   ` | `- ` |
| ตัวเอียง `*ข้อความ*` | ตัด `*` ออก (ตัวหนา `**` คงไว้) |
| "ค่ะ" / "ดิฉัน" (บอทใช้ "ผม/ครับ") | "ครับ" / "ผม" |
| emoji | ตัดออก |
| "1 พ.ค. 2569" ทั้งที่ข้อมูลคือ "1 พ.ย. 2569" | แก้เป็นวันที่ในผลของเครื่องมือ (ดู `known_dates`) |

ข้อความไหลมาทีละชิ้น จึงกันท้ายไว้ `HOLD_CHARS` ตัวอักษรรอชิ้นถัดไป เผื่อคำที่ต้องแก้ถูกแบ่งคนละชิ้น
"""

import re
from collections.abc import Iterable

from ..processing.formatter import THAI_MONTHS

HOLD_CHARS = 16  # ยาวกว่าคำที่ยาวที่สุดที่ต้องแก้ ("31 มี.ค. 2569", "เหรอคะ" + "แนน")

_BULLET = re.compile(r"(?m)^([ \t]*)\*(?!\*)[ \t]+")
_BULLET_SPACES = re.compile(r"(?m)^([ \t]*)- [ \t]+(?=\S)")  # "*   " ที่มาทีละตัว เหลือช่องว่างเกิน
_TRIPLE_STAR = re.compile(r"\*{3,}")
_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)")
_ITALIC_STAR_NOT_LAST = re.compile(r"(?<!\*)\*(?![*]|\Z)")  # ดาวตัวสุดท้ายอาจเป็นครึ่งแรกของ **
_KHA = re.compile(r"ค่ะ")
_KHA_QUESTION = re.compile(r"(นะ|ไหม|มั้ย|หรือ|เหรอ|ไหน)คะ(?!แนน)")
# ยังไม่รู้ตัวถัดไป → รอก่อน เผื่อเป็น "คะแนน"
_KHA_QUESTION_NOT_LAST = re.compile(r"(นะ|ไหม|มั้ย|หรือ|เหรอ|ไหน)คะ(?!แนน|แน\Z|แ\Z|\Z)")
_DICHAN = re.compile(r"ดิฉัน")
_DOUBLE_KHRAP = re.compile(r"ครับ(?:[ ]?ครับ)+")
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⭐⭕️‍]")

_MONTHS = "|".join(re.escape(month) for month in THAI_MONTHS)
_THAI_DATE = re.compile(rf"(?<!\d)(\d{{1,2}}) ({_MONTHS})(?: (\d{{4}}))?")


def known_dates(texts: Iterable[str]) -> set[tuple[str, str, str | None]]:
    """วันที่แบบไทยที่มีอยู่ในผลของเครื่องมือ เก็บทั้งแบบมีปีและไม่มีปี"""
    found: set[tuple[str, str, str | None]] = set()
    for text in texts:
        for day, month, year in _THAI_DATE.findall(text):
            found.add((day, month, None))
            if year:
                found.add((day, month, year))
    return found


class AnswerCleaner:
    """ตัวกรองแบบ stream: `feed()` ทีละชิ้น แล้ว `flush()` ตอนจบ"""

    def __init__(self) -> None:
        self._held = ""
        self._at_line_start = True  # ข้อความที่ส่งไปแล้วจบที่ต้นบรรทัด (หรือมีแค่ช่องว่างหลังขึ้นบรรทัด)
        self._dates: set[tuple[str, str, str | None]] = set()

    def learn_dates(self, text: str) -> None:
        """จำวันที่จากผลของเครื่องมือ ใช้แก้วันที่ที่โมเดลพิมพ์เดือนผิด"""
        self._dates |= known_dates([text])

    def feed(self, text: str) -> str:
        if not text:
            return ""
        cleaned = self._clean(self._held + text, final=False)
        cut = _safe_cut(cleaned)
        self._held = cleaned[cut:]
        return self._sent(cleaned[:cut])

    def flush(self) -> str:
        text = self._clean(self._held, final=True)
        self._held = ""
        return self._sent(text)

    def _sent(self, text: str) -> str:
        if text:
            line = text.rsplit("\n", 1)
            self._at_line_start = (len(line) == 2 or self._at_line_start) and not line[-1].strip()
        return text

    def _clean(self, text: str, *, final: bool) -> str:
        # ใส่ตัวนำหน้าชั่วคราวเพื่อให้ ^ ของ regex รู้ว่าข้อความต่อจากต้นบรรทัดหรือกลางบรรทัด
        lead = "\n" if self._at_line_start else "x"
        text = _BULLET_SPACES.sub(r"\1- ", _BULLET.sub(r"\1- ", lead + text))[1:]
        text = _TRIPLE_STAR.sub("**", text)
        text = (_ITALIC_STAR if final else _ITALIC_STAR_NOT_LAST).sub("", text)
        text = _KHA.sub("ครับ", text)
        text = (_KHA_QUESTION if final else _KHA_QUESTION_NOT_LAST).sub(r"\1ครับ", text)
        text = _DICHAN.sub("ผม", text)
        text = _DOUBLE_KHRAP.sub("ครับ", text)
        text = _EMOJI.sub("", text)
        return _THAI_DATE.sub(self._fix_date, text) if self._dates else text

    def _fix_date(self, match: re.Match[str]) -> str:
        day, month, year = match.groups()
        if (day, month, year) in self._dates:
            return match.group(0)
        # เดือนที่ต่างกัน 1 ตัวอักษร (พ.ค./พ.ย.) และมีวันที่นั้นในข้อมูลจริงเพียงแบบเดียว → โมเดลพิมพ์ผิด
        candidates = [
            other
            for other in THAI_MONTHS
            if _one_char_apart(other, month) and (day, other, year) in self._dates
        ]
        if len(candidates) != 1:
            return match.group(0)
        return match.group(0).replace(month, candidates[0], 1)


def _safe_cut(text: str) -> int:
    """จุดตัดระหว่างส่วนที่ส่งได้กับส่วนที่ต้องกันไว้ ไม่ตัดติดกับ * (อาจเป็น ** ที่ยังมาไม่ครบ)"""
    cut = max(0, len(text) - HOLD_CHARS)
    while cut > 0 and (text[cut - 1] == "*" or text[cut] == "*"):
        cut -= 1
    return cut


def _one_char_apart(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1
