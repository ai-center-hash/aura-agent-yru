"""ลบประวัติแชทที่ไม่มีการใช้งานนาน (Phase 6 · Operations)

    python -m uv run python scripts/prune_threads.py --dry-run     # ดูก่อนว่าจะลบกี่ห้อง
    python -m uv run python scripts/prune_threads.py               # ลบจริง

บนเครื่อง yru-ai รันวันละครั้งด้วย `aura-prune.timer` (ติดตั้งโดย deploy/install.sh)
ค่าเริ่มต้น: ห้องของผู้ใช้ที่เข้าสู่ระบบเก็บ 30 วัน · ผู้ใช้ที่ไม่ได้เข้าสู่ระบบเก็บ 1 วัน
พิมพ์แค่จำนวน ไม่พิมพ์ thread_id เพราะมี subject ของผู้ใช้อยู่ข้างใน

ไฟล์ SQLite ไม่หดลงหลังลบ (SQLite เอาพื้นที่ว่างไปใช้ซ้ำเอง) ไม่ต้อง VACUUM ระหว่างที่ service รันอยู่
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from aura_agent.agent import prune_threads, sqlite_checkpointer
from aura_agent.config import get_settings

DEFAULT_DAYS = 30
DEFAULT_ANONYMOUS_DAYS = 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ลบประวัติแชทที่ไม่มีการใช้งานนาน")
    parser.add_argument("--days", type=float, default=DEFAULT_DAYS, help="ผู้ใช้ที่เข้าสู่ระบบ")
    parser.add_argument(
        "--anonymous-days",
        type=float,
        default=DEFAULT_ANONYMOUS_DAYS,
        help="ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ",
    )
    parser.add_argument("--sqlite-path", help="ไม่ใส่ = SQLITE_PATH ใน .env")
    parser.add_argument("--dry-run", action="store_true", help="นับอย่างเดียว ไม่ลบ")
    args = parser.parse_args(argv)
    if args.days <= 0 or args.anonymous_days <= 0:
        parser.error("--days และ --anonymous-days ต้องมากกว่า 0")
    return args


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = args.sqlite_path or get_settings().sqlite_path

    async with sqlite_checkpointer(path) as saver:
        result = await prune_threads(
            saver,
            now=datetime.now(UTC),
            max_age=timedelta(days=args.days),
            anonymous_max_age=timedelta(days=args.anonymous_days),
            dry_run=args.dry_run,
        )

    verb = "จะลบ" if args.dry_run else "ลบแล้ว"
    print(
        f"ตรวจ {result.checked} ห้อง · {verb} {result.deleted} ห้อง"
        f" (ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ {result.deleted_anonymous})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
