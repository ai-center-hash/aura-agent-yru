"""persona จำลอง: ActClient ที่อ่านจาก fixture และกรองเหมือน Activity API

ทำให้ eval รู้คำตอบที่ถูกแน่นอนและรันซ้ำได้ (LLM เท่านั้นที่เป็นของจริง)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from aura_agent.data import (
    NoActivityFrame,
    NotAnAdmin,
    NotAStudent,
    NotYourAdvisee,
    UpstreamNotFound,
)
from aura_agent.data.schemas import (
    Advisee,
    PassportUser,
    Registration,
    Schedule,
    StudentSummary,
)

PERSONA_DIR = Path(__file__).parent / "personas"

# วันอ้างอิงของ fixture ทุกชุด — ตรึงไว้เพื่อให้ผล eval ไม่เปลี่ยนตามวันที่รัน
EVAL_TODAY = date(2026, 10, 20)

EVAL_JWT = "eval.fixture.jwt"  # ไม่ใช่ token จริง persona ไม่ได้ตรวจค่านี้


@dataclass(frozen=True)
class Persona:
    """นักศึกษา (มี `summary_me.json`) หรือบุคลากร (มี `identity.json` แทน ไม่มีข้อมูลกิจกรรม)"""

    name: str
    summary: StudentSummary | None
    schedules: list[Schedule]
    registrations: list[Registration]
    identity: PassportUser | None = None
    # อาจารย์ที่ปรึกษา: แถวจาก /v1/auth/users และ summary ของแต่ละคน (คนที่ไม่มีไฟล์ = ยังไม่มีกรอบ)
    advisees: list[Advisee] = field(default_factory=list)
    advisee_summaries: dict[str, StudentSummary] = field(default_factory=dict)
    # ผู้ดูแลระบบ (role admin ในระบบกิจกรรม): ดูได้ทุกรหัสที่มีไฟล์ใน student_summaries/
    is_admin: bool = False
    student_summaries: dict[str, StudentSummary] = field(default_factory=dict)

    @property
    def is_student(self) -> bool:
        return self.summary is not None

    @property
    def is_anonymous(self) -> bool:
        """ไม่ได้เข้าสู่ระบบ: eval ส่ง jwt=None เหมือน backend ไม่ส่ง Authorization"""
        return self.summary is None and self.identity is None

    @property
    def user_id(self) -> int | None:
        return self.summary.user.id if self.summary is not None else None

    @property
    def subject(self) -> str:
        """id ที่ใช้แยกประวัติแชท (เหมือน `ActClient.get_subject`)"""
        if self.summary is not None:
            return str(self.summary.user.id)
        if self.identity is None:
            return "anonymous"
        return f"passport:{self.identity.sub}"


def load_persona(name: str, directory: Path | None = None) -> Persona:
    base = (directory or PERSONA_DIR) / name
    if not base.is_dir():
        raise FileNotFoundError(f"ไม่พบ persona: {base}")

    schedules = [Schedule.model_validate(row) for row in _read(base / "schedules.json")["data"]]
    if (base / "anonymous.json").exists():
        return Persona(name=name, summary=None, schedules=schedules, registrations=[])
    if (base / "identity.json").exists():
        identity = PassportUser.model_validate(_read(base / "identity.json"))
        advisees: list[Advisee] = []
        if (base / "advisees.json").exists():
            advisees = [
                Advisee.model_validate(row) for row in _read(base / "advisees.json")["data"]
            ]
        summaries = {
            path.stem: StudentSummary.model_validate(_read(path)["data"])
            for path in sorted((base / "advisee_summaries").glob("*.json"))
        }
        student_summaries = {
            path.stem: StudentSummary.model_validate(_read(path)["data"])
            for path in sorted((base / "student_summaries").glob("*.json"))
        }
        return Persona(
            name=name,
            summary=None,
            schedules=schedules,
            registrations=[],
            identity=identity,
            advisees=advisees,
            advisee_summaries=summaries,
            is_admin=(base / "admin.json").exists(),
            student_summaries=student_summaries,
        )

    summary = StudentSummary.model_validate(_read(base / "summary_me.json")["data"])
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
        return self.persona.subject

    async def get_my_summary(self, jwt: str) -> StudentSummary:
        self.calls.append(("get_my_summary", {}))
        if self.persona.summary is None:
            # เหมือน ActClient โหมด passport เมื่อเจ้าของ token เป็นบุคลากร
            raise NotAStudent("persona บุคลากร", identity=self.persona.identity)
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

    async def get_advisees(self, jwt: str) -> list[Advisee]:
        self.calls.append(("get_advisees", {}))
        return list(self.persona.advisees) if not self.persona.is_student else []

    async def get_advisee_summary(self, jwt: str, student_code: str):
        """เหมือน ActClient: ตรวจรายชื่อที่ปรึกษาก่อนเสมอ"""
        code = student_code.strip()
        self.calls.append(("get_advisee_summary", {"code": code}))
        advisee = next((row for row in await self.get_advisees(jwt) if row.username == code), None)
        if advisee is None:
            raise NotYourAdvisee("persona")
        summary = self.persona.advisee_summaries.get(code)
        if summary is None:
            raise NoActivityFrame("ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้")
        return advisee, summary

    async def is_admin(self, jwt: str) -> bool:
        self.calls.append(("is_admin", {}))
        return self.persona.is_admin

    async def get_student_summary_as_admin(self, jwt: str, student_code: str):
        """เหมือน ActClient: ตรวจสิทธิ์ผู้ดูแลระบบก่อนเสมอ · รหัสที่ไม่มีไฟล์ = ไม่พบในระบบ (404)"""
        code = student_code.strip()
        self.calls.append(("get_student_summary_as_admin", {"code": code}))
        if not self.persona.is_admin:
            raise NotAnAdmin("persona")
        summary = self.persona.student_summaries.get(code)
        if summary is None:
            raise UpstreamNotFound("persona: HTTP 404")
        user = summary.user
        student = Advisee(
            username=code, name=user.name, program=user.major, student_status=user.student_status
        )
        return student, summary

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
