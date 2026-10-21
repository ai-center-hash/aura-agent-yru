"""ประวัติแชท (checkpointer)

ใช้ serializer ที่อนุญาต `StudentProfile` ไว้ชัดเจน เพราะ langgraph จะบล็อกชนิดที่ไม่ได้ลงทะเบียน
ในเวอร์ชันถัดไป (ค่าเริ่มต้นตอนนี้แค่เตือน)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..config import get_settings

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
