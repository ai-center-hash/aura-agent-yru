"""ตรวจว่าคำตอบของโมเดลอ้างข้อมูลที่ "มีจริง" ใน persona หรือไม่

eval ปกติตรวจว่าคำตอบ**มี**ข้อความที่ต้องมี (`must_contain`) แต่ไม่ได้ตรวจว่าโมเดล
**เพิ่ม**ข้อมูลที่ไม่มีอยู่จริงเข้ามาด้วยหรือเปล่า ไฟล์นี้ปิดช่องนั้น

    python -m uv run python tests/evals/data_audit.py <ไฟล์ json จาก run_evals --json>

ตรวจ 4 อย่างจากข้อมูลใน `tests/evals/personas/`
1. เรียกเครื่องมือก่อนตอบหรือไม่ (คำถามกลุ่ม search/recommend/history ต้องเรียก)
2. ชื่อกิจกรรมที่พูดถึง มีอยู่ใน persona จริงไหม
3. วันที่ที่พูดถึง ตรงกับวันในข้อมูลไหม (วันจัด วันรับสมัคร วันเช็คอิน หรือ "วันนี้")
4. ปี พ.ศ. ที่พูดถึง อยู่ในช่วงที่ข้อมูลมีได้ไหม
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):  # รันเป็น script
    sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.evals.personas import EVAL_TODAY, Persona, available_personas, load_persona

BUDDHIST_OFFSET = 543
TITLE_MATCH_LEN = 12  # ตัดหัวชื่อกิจกรรมมาเทียบ เพราะโมเดลมักตัดคำท้ายหรือเติม "กิจกรรม" ข้างหน้า

# กลุ่มคำถามที่ข้อมูลไม่ได้อยู่ใน system prompt จึงต้องเรียกเครื่องมือก่อนตอบ
TOOL_REQUIRED_CATEGORIES = {"search", "recommend", "history"}

THAI_MONTHS = {
    "ม.ค.": 1, "มกราคม": 1,
    "ก.พ.": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เมษายน": 4,
    "พ.ค.": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "กันยายน": 9,
    "ต.ค.": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธันวาคม": 12,
}  # fmt: skip

_MONTH_PATTERN = "|".join(re.escape(name) for name in sorted(THAI_MONTHS, key=len, reverse=True))
DATE_RE = re.compile(rf"(\d{{1,2}})\s*({_MONTH_PATTERN})\s*(\d{{4}})")
YEAR_RE = re.compile(r"\b(25\d{2})\b")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PersonaFacts:
    """ข้อเท็จจริงทั้งหมดที่คำตอบ "อ้างได้" สำหรับ persona นี้"""

    titles: set[str]
    date_keys: set[tuple[int, int, int]]  # (วัน, เดือน, ปี พ.ศ.)
    years: set[int]

    @property
    def title_keys(self) -> set[str]:
        return {normalize(title)[:TITLE_MATCH_LEN] for title in self.titles if title}


@dataclass
class AnswerAudit:
    case_id: str
    category: str
    persona: str
    tools_used: list[str]
    known_titles: list[str] = field(default_factory=list)
    unknown_dates: list[str] = field(default_factory=list)
    unknown_years: list[int] = field(default_factory=list)

    @property
    def tool_missing(self) -> bool:
        return self.category in TOOL_REQUIRED_CATEGORIES and not self.tools_used

    @property
    def fabricated(self) -> bool:
        return bool(self.unknown_dates or self.unknown_years)

    @property
    def clean(self) -> bool:
        return not self.fabricated and not self.tool_missing


def normalize(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def collect_facts(persona: Persona, today: date = EVAL_TODAY) -> PersonaFacts:
    titles: set[str] = set()
    moments: list[datetime] = []
    dates: set[tuple[int, int, int]] = {(today.day, today.month, today.year + BUDDHIST_OFFSET)}

    for schedule in persona.schedules:
        if schedule.activity:
            titles.add(schedule.activity.title)
        moments += [
            schedule.activity_start_date,
            schedule.activity_end_date,
            schedule.registration_start_date,
            schedule.registration_end_date,
        ]

    for registration in persona.registrations:
        if registration.activity:
            titles.add(registration.activity.title)
        moments += [registration.registered_at, registration.checkin_at, registration.checkout_at]
        if registration.schedule:
            moments += [
                registration.schedule.activity_start_date,
                registration.schedule.activity_end_date,
            ]

    categories = persona.summary.categories if persona.summary is not None else []
    for category in categories:
        for item in category.frame_items:
            for activity in item.activities:
                titles.add(activity.title)
                moments += [activity.checkin_at, activity.checkout_at]

    frame = persona.summary.frame if persona.summary is not None else None
    if frame:
        for day in (frame.start_date, frame.end_date):
            if day is not None:
                dates.add((day.day, day.month, day.year + BUDDHIST_OFFSET))

    for moment in moments:
        if moment is not None:
            dates.add((moment.day, moment.month, moment.year + BUDDHIST_OFFSET))

    return PersonaFacts(titles=titles, date_keys=dates, years={year for _, _, year in dates})


def find_dates(text: str) -> list[tuple[int, int, int]]:
    return [(int(day), THAI_MONTHS[month], int(year)) for day, month, year in DATE_RE.findall(text)]


def find_years(text: str) -> list[int]:
    return [int(year) for year in YEAR_RE.findall(text)]


def audit_answer(
    *,
    case_id: str,
    category: str,
    persona_name: str,
    answer: str,
    tools_used: list[str],
    facts: PersonaFacts,
) -> AnswerAudit:
    text = normalize(answer)
    audit = AnswerAudit(
        case_id=case_id, category=category, persona=persona_name, tools_used=list(tools_used)
    )

    for key in facts.title_keys:
        if key and key in text:
            audit.known_titles.append(key)

    for day, month, year in find_dates(text):
        if (day, month, year) not in facts.date_keys:
            audit.unknown_dates.append(f"{day}/{month}/{year}")

    allowed_years = facts.years
    for year in find_years(text):
        if year not in allowed_years:
            audit.unknown_years.append(year)

    return audit


def audit_dump(path: Path) -> tuple[dict, list[AnswerAudit]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    facts = {name: collect_facts(load_persona(name)) for name in available_personas()}

    audits = [
        audit_answer(
            case_id=case["id"],
            category=case["category"],
            persona_name=case["persona"],
            answer=case["answer"],
            tools_used=case["tools_used"],
            facts=facts[case["persona"]],
        )
        for case in payload["cases"]
    ]
    return payload, audits


def render_audit(payload: dict, audits: list[AnswerAudit]) -> str:
    total = len(audits)
    fabricated = [audit for audit in audits if audit.fabricated]
    tool_missing = [audit for audit in audits if audit.tool_missing]
    grounded = [audit for audit in audits if audit.known_titles]

    lines = [
        f"# ตรวจความถูกต้องของข้อมูลในคำตอบ · {payload['model']} · {payload['started_at']}",
        "",
        f"- จำนวนคำตอบที่ตรวจ: **{total}**",
        f"- อ้างชื่อกิจกรรมที่มีอยู่จริง: **{len(grounded)}**",
        f"- กุข้อมูล (วันที่หรือปีที่ไม่มีในข้อมูล): **{len(fabricated)}**",
        f"- ไม่เรียกเครื่องมือทั้งที่ต้องเรียก: **{len(tool_missing)}**",
        "",
        "| id | หมวด | เครื่องมือ | ชื่อกิจกรรมที่ตรงข้อมูล | วันที่ที่ไม่มีในข้อมูล | ปีที่ไม่มีในข้อมูล |",
        "|---|---|---|---|---|---|",
    ]
    for audit in audits:
        lines.append(
            f"| {audit.case_id} | {audit.category} | {','.join(audit.tools_used) or '-'} |"
            f" {len(audit.known_titles)} |"
            f" {', '.join(audit.unknown_dates) or '-'} |"
            f" {', '.join(str(year) for year in audit.unknown_years) or '-'} |"
        )

    if fabricated:
        lines += ["", "## คำตอบที่พบการกุข้อมูล", ""]
        for audit in fabricated:
            lines.append(
                f"- **{audit.case_id}**: วันที่ {', '.join(audit.unknown_dates) or '-'}"
                f" · ปี {', '.join(str(year) for year in audit.unknown_years) or '-'}"
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    payload, audits = audit_dump(Path(args[0]))
    report = render_audit(payload, audits)
    print(report)

    if len(args) > 1:
        out = Path(args[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"เขียนรายงานที่ {out}")

    return 1 if any(audit.fabricated or audit.tool_missing for audit in audits) else 0


if __name__ == "__main__":
    sys.exit(main())
