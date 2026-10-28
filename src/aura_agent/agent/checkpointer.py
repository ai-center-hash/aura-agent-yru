"""ประวัติแชท (checkpointer)

ใช้ serializer ที่อนุญาต `StudentProfile` ไว้ชัดเจน เพราะ langgraph จะบล็อกชนิดที่ไม่ได้ลงทะเบียน
ในเวอร์ชันถัดไป (ค่าเริ่มต้นตอนนี้แค่เตือน)

`prune_threads` ลบ thread ที่ไม่มีการใช้งานนาน (เรียกจาก `scripts/prune_threads.py` วันละครั้ง)
เพราะประวัติแชทมีผลของ tool ที่เป็นข้อมูลส่วนตัวของนักศึกษา จึงไม่เก็บไว้ตลอด
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..config import get_settings
from .graph import ANONYMOUS_SUBJECT

ALLOWED_STATE_TYPES = [("aura_agent.processing.models", "StudentProfile")]


def state_serializer() -> JsonPlusSerializer:
    """serializer ที่อ่าน/เขียน `StudentProfile` ใน state ได้"""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_STATE_TYPES)


@asynccontextmanager
async def sqlite_checkpointer(path: str | None = None) -> AsyncIterator[AsyncSqliteSaver]:
    """เปิดไฟล์ SQLite สำหรับเก็บประวัติแชท (สร้างโฟลเดอร์ให้ถ้ายังไม่มี)"""
    sqlite_path = Path(path or get_settings().sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(sqlite_path) as connection:
        yield AsyncSqliteSaver(connection, serde=state_serializer())


@dataclass(frozen=True, slots=True)
class PruneResult:
    """จำนวน thread ที่ตรวจและที่ลบ (ไม่เก็บ thread_id เพราะมี subject ของผู้ใช้อยู่ข้างใน)"""

    checked: int
    deleted: int
    deleted_anonymous: int


async def prune_threads(
    saver: AsyncSqliteSaver,
    *,
    now: datetime,
    max_age: timedelta,
    anonymous_max_age: timedelta,
    dry_run: bool = False,
) -> PruneResult:
    """ลบ thread ที่ checkpoint ล่าสุดเก่ากว่ากำหนด · ผู้ใช้ที่ไม่ได้เข้าสู่ระบบใช้ `anonymous_max_age`

    `now` ต้องมี timezone (เวลาใน checkpoint เป็น UTC) · `dry_run=True` นับอย่างเดียวไม่ลบ
    """
    await saver.setup()
    async with saver.lock, saver.conn.execute("SELECT DISTINCT thread_id FROM checkpoints") as cur:
        thread_ids = [str(row[0]) for row in await cur.fetchall()]

    deleted = deleted_anonymous = 0
    for thread_id in thread_ids:
        latest = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        if latest is None:
            continue
        anonymous = thread_id.startswith(f"{ANONYMOUS_SUBJECT}:")
        limit = anonymous_max_age if anonymous else max_age
        if now - datetime.fromisoformat(latest.checkpoint["ts"]) <= limit:
            continue
        if not dry_run:
            await saver.adelete_thread(thread_id)
        deleted += 1
        deleted_anonymous += anonymous

    return PruneResult(
        checked=len(thread_ids), deleted=deleted, deleted_anonymous=deleted_anonymous
    )
