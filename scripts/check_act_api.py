"""ทดสอบ ActClient กับ Activity API จริง เพื่อปิด DoD ของ Phase 0–1 และตอบ Q1–Q5

วิธีใช้ (ห้ามใส่ token เป็น argument จะค้างใน shell history):

    set AURA_DEV_JWT=<JWT ของผู้พัฒนาเอง>       # PowerShell: $env:AURA_DEV_JWT="..."
    python -m uv run python scripts/check_act_api.py

script นี้พิมพ์แค่ "มีฟิลด์ไหน / กี่รายการ / ค่าที่ไม่ใช่ข้อมูลส่วนบุคคล" เท่านั้น
**ห้ามคัดลอก response จริง ชื่อ อีเมล หรือรหัสนักศึกษาไปใส่ใน docs หรือ fixture**
"""

import asyncio
import os
import sys

import httpx

from aura_agent.config import get_settings
from aura_agent.data import ActClient, NoActivityFrame, NullCache, build_act_client
from aura_agent.data.errors import ActApiError

ACTIVITIES_PATH = "/v1/act/activities"  # endpoint D (Student Mode) สำหรับ Q3


def line(label: str, value: object) -> None:
    print(f"  {label}: {value}")


async def check_summary(client: ActClient, jwt: str) -> int | None:
    """ตัวตนของเจ้าของ token และความคืบหน้า (เส้นทางตาม IDENTITY_MODE ใน .env)"""
    print(f"\n[A] ความคืบหน้าของเจ้าของ token (โหมด {client.identity_mode})")
    try:
        identity = await client.get_identity(jwt)
        if identity is not None:
            line("Passport user_type", identity.user_type)
            line("รหัสนักศึกษา", f"ยาว {len(identity.student_code or '')} ตัว (ไม่พิมพ์ค่า)")
            line("คณะจาก Passport", identity.org_unit_1_name)
        summary = await client.get_my_summary(jwt)
    except NoActivityFrame as missing:
        line("ผล", f"ยังไม่มีกรอบกิจกรรม · {missing.detail}")
        return None
    except ActApiError as error:
        line("ไม่สำเร็จ", f"{type(error).__name__} · {error.code} · {error.detail}")
        return None

    line("parse เข้า schema", "สำเร็จ")
    line("user.id", "มีค่า" if summary.user.id else "ไม่มี")
    line("student_status", summary.user.student_status)
    line(
        "มี student_id/faculty/major",
        [
            summary.user.student_id is not None,
            summary.user.faculty is not None,
            summary.user.major is not None,
        ],
    )
    line("frame", summary.frame.title if summary.frame else "ไม่มี frame")
    line(
        "summary", f"{summary.summary.total_activities} กิจกรรม / {summary.summary.total_hours} ชม."
    )
    line("overall_status", summary.summary.overall_status)
    line("จำนวน categories", len(summary.categories))
    for category in summary.categories:
        items = category.frame_items
        requirement = items[0].requirement if items else None
        line(
            f"  category_id={category.category_id} ({category.type_name})",
            f"frame_items={len(items)} "
            + (
                f"normal={requirement.normal_activity_min}act/{requirement.normal_hour_min}hr "
                f"transfer={requirement.transfer_activity_min}act/{requirement.transfer_hour_min}hr"
                if requirement
                else "ไม่มี requirement"
            ),
        )
    return summary.user.id


async def check_schedules(client: ActClient, jwt: str) -> None:
    """Q4: ดูว่า target_student_year_prefix ส่งค่าอะไรมาจริง"""
    print("\n[B] GET /v1/act/activity-schedules?registration_phase=open")
    try:
        schedules = await client.get_schedules(jwt, phase="open")
    except ActApiError as error:
        line("ไม่สำเร็จ", f"{type(error).__name__} · {error.code} · {error.detail}")
        return

    line("จำนวนรอบที่เปิดรับสมัคร", len(schedules))
    restricted = [schedule for schedule in schedules if schedule.is_restricted]
    line("รอบที่จำกัดกลุ่มเป้าหมาย", len(restricted))
    for schedule in restricted[:5]:
        line(
            f"  schedule_id={schedule.id}",
            f"year_prefix={schedule.target_student_year_prefix} "
            f"faculties={len(schedule.target_faculties)} รายการ "
            f"status={schedule.target_student_status}",
        )
    missing_category = [schedule.id for schedule in schedules if schedule.category_id is None]
    line("รอบที่ไม่มี category_id", missing_category[:5] or "ไม่มี")


async def check_registrations(client: ActClient, jwt: str, user_id: int) -> None:
    print(f"\n[C] GET /v1/act/act-registrations?user_id={user_id}")
    try:
        registrations = await client.get_registrations(jwt, user_id)
    except ActApiError as error:
        line("ไม่สำเร็จ", f"{type(error).__name__} · {error.code} · {error.detail}")
        return

    line("จำนวนรายการ", len(registrations))
    statuses: dict[int, int] = {}
    for registration in registrations:
        statuses[registration.status] = statuses.get(registration.status, 0) + 1
    line("นับตาม status", dict(sorted(statuses.items())))
    line("มี schedule ซ้อนมาด้วย", any(r.schedule is not None for r in registrations))


async def check_student_mode(base_url: str, jwt: str, timeout_s: float) -> None:
    """Q3: endpoint D (Student Mode) กรองตามสิทธิ์ของผู้ที่ login ไหม

    เทียบจำนวนรายการ "ส่ง token" กับ "ไม่ส่ง token" ถ้าต่างกันแปลว่ากรองตามผู้ใช้
    """
    print(f"\n[D] GET {ACTIVITIES_PATH} (Student Mode) — Q3")
    params = {"paginate": "false"}
    async with httpx.AsyncClient(
        base_url=base_url, timeout=timeout_s, headers={"Accept": "application/json"}
    ) as raw:
        for label, headers in (
            ("ส่ง token", {"Authorization": f"Bearer {jwt}"}),
            ("ไม่ส่ง token", {}),
        ):
            try:
                response = await raw.get(ACTIVITIES_PATH, params=params, headers=headers)
            except httpx.HTTPError as error:
                line(label, f"ต่อไม่ได้: {type(error).__name__}")
                continue
            if response.status_code >= 400:
                line(label, f"HTTP {response.status_code}")
                continue
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            line(label, f"HTTP 200 · {len(rows) if isinstance(rows, list) else '?'} รายการ")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                line(f"  ฟิลด์ของแถวแรก ({label})", sorted(rows[0].keys()))


async def check_registrations_public(base_url: str, user_id: int, timeout_s: float) -> None:
    """Q5: endpoint C เรียกได้โดยไม่ส่ง token จริงไหม (ถ้าได้ ต้องระวัง user_id เป็นพิเศษ)"""
    print("\n[C-public] GET /v1/act/act-registrations โดยไม่ส่ง token — Q5")
    async with httpx.AsyncClient(
        base_url=base_url, timeout=timeout_s, headers={"Accept": "application/json"}
    ) as raw:
        try:
            response = await raw.get(
                "/v1/act/act-registrations",
                params={"paginate": "false", "user_id": str(user_id)},
            )
        except httpx.HTTPError as error:
            line("ผล", f"ต่อไม่ได้: {type(error).__name__}")
            return
    if response.status_code >= 400:
        line("ผล", f"HTTP {response.status_code} → ต้องใช้ token")
        return
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    line(
        "ผล", f"HTTP 200 · {len(rows) if isinstance(rows, list) else '?'} รายการ → เป็น public route"
    )


async def main() -> int:
    jwt = os.environ.get("AURA_DEV_JWT", "").strip()
    if not jwt:
        print("ไม่พบ AURA_DEV_JWT ใน environment (ดูวิธีใช้ใน docstring ของไฟล์นี้)")
        return 2

    settings = get_settings()
    print(f"Activity API: {settings.act_api_base_url}")
    print("หมายเหตุ: ข้อมูลที่ยิงเป็นข้อมูลจริง ห้ามคัดลอก response ไปเก็บไว้ในโปรเจ็ค")

    async with build_act_client(settings, cache=NullCache()) as client:
        line("\nping()", await client.ping())
        user_id = await check_summary(client, jwt)
        await check_schedules(client, jwt)
        if user_id is not None:
            await check_registrations(client, jwt, user_id)
        await check_student_mode(settings.act_api_base_url, jwt, settings.act_api_timeout_s)
        if user_id is not None:
            await check_registrations_public(
                settings.act_api_base_url, user_id, settings.act_api_timeout_s
            )

    print("\nเสร็จแล้ว — บันทึกผล Q1–Q5 ลง HANDOFF.md โดยสรุปเป็นข้อความ ไม่ใส่ response จริง")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
