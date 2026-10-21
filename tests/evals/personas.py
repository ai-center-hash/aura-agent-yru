"""persona จำลอง: ActClient ที่อ่านจาก fixture และกรองเหมือน Activity API

ทำให้ eval รู้คำตอบที่ถูกแน่นอนและรันซ้ำได้ (LLM เท่านั้นที่เป็นของจริง)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from aura_agent.data.schemas import Registration, Schedule, StudentSummary

PERSONA_DIR = Path(__file__).parent / "personas"

# วันอ้างอิงของ fixture ทุกชุด — ตรึงไว้เพื่อให้ผล eval ไม่เปลี่ยนตามวันที่รัน
EVAL_TODAY = date(2026, 10, 20)

EVAL_JWT = "eval.fixture.jwt"  # ไม่ใช่ token จริง persona ไม่ได้ตรวจค่านี้


@dataclass(frozen=True)
class Persona:
    name: str
    summary: StudentSummary
    schedules: list[Schedule]
    registrations: list[Registration]

    @property
    def user_id(self) -> int:
        return self.summary.user.id


def load_persona(name: str, directory: Path | None = None) -> Persona:
    base = (directory or PERSONA_DIR) / name
    if not base.is_dir():
        raise FileNotFoundError(f"ไม่พบ persona: {base}")

    summary = StudentSummary.model_validate(_read(base / "summary_me.json")["data"])
    schedules = [Schedule.model_validate(row) for row in _read(base / "schedules.json")["data"]]
    registrations = [
        Registration.model_validate(row) for row in _read(base / "registrations.json")["data"]
    ]
    return Persona(name=name, summary=summary, schedules=schedules, registrations=registrations)


def available_personas(directory: Path | None = None) -> list[str]:
    base = directory or PERSONA_DIR
    return sorted(path.name for path in base.iterdir() if path.is_dir())


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PersonaClient:
    """มี interface เหมือน `ActClient` เท่าที่ tool เรียกใช้

    กรองแบบเดียวกับที่ Activity API กรองฝั่ง server เพื่อให้ผลที่ LLM เห็นสมจริง
    """

    def __init__(self, persona: Persona, today: date = EVAL_TODAY) -> None:
        self.persona = persona
        self.today = today
        self.calls: list[tuple[str, dict]] = []

    async def get_subject(self, jwt: str) -> str:
        return str(self.persona.user_id)

    async def get_my_summary(self, jwt: str) -> StudentSummary:
        self.calls.append(("get_my_summary", {}))
        return self.persona.summary

    async def get_schedules(
        self,
        jwt: str,
        *,
        phase: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
    ) -> list[Schedule]:
        self.calls.append(
            ("get_schedules", {"phase": phase, "from": date_from, "to": date_to, "search": search})
        )

        # fixture มีแต่รอบที่เผยแพร่แล้ว
        # (schema ไม่เก็บ is_published เพราะ client ส่ง is_published=true เสมอ)
        rows = list(self.persona.schedules)
        if phase == "open":
            rows = [row for row in rows if row.is_registration_open]
        elif phase == "upcoming":
            rows = [row for row in rows if self._is_upcoming(row)]
        if date_from is not None:
            rows = [row for row in rows if self._activity_date(row) >= date_from]
        if date_to is not None:
            rows = [row for row in rows if self._activity_date(row) <= date_to]
        if search:
            needle = search.strip().lower()
            rows = [row for row in rows if needle in self._title(row).lower()]
        return rows

    async def get_registrations(self, jwt: str, user_id: int) -> list[Registration]:
        self.calls.append(("get_registrations", {"user_id": user_id}))
        if user_id != self.persona.user_id:
            return []  # เหมือน API: ถาม user อื่นก็ไม่เจอข้อมูลใน fixture นี้
        return self.persona.registrations

    async def ping(self) -> bool:
        return True

    # ---- ภายใน ----

    def _is_upcoming(self, schedule: Schedule) -> bool:
        start = schedule.registration_start_date
        return not schedule.is_registration_open and start is not None and start.date() > self.today

    @staticmethod
    def _activity_date(schedule: Schedule) -> date:
        start = schedule.activity_start_date
        return start.date() if start is not None else date.max

    @staticmethod
    def _title(schedule: Schedule) -> str:
        return schedule.activity.title if schedule.activity else ""
