"""test ของการลบประวัติแชทที่ไม่มีการใช้งาน (agent.prune_threads และ scripts/prune_threads.py)"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aura_agent.agent import build_graph, prune_threads, run_config, sqlite_checkpointer

from .conftest import JWT

SCRIPT = Path(__file__).parents[2] / "scripts" / "prune_threads.py"
ANON_THREAD = "c1f0a7e2-5b3d-4f6a-9e8c-2d7b1a0f4e6c"
DAYS_30 = timedelta(days=30)
DAY_1 = timedelta(days=1)


@pytest.fixture
async def chat_db(act_client, frozen_today, llm, tmp_path):
    """SQLite ที่มี 3 ห้อง: นักศึกษา 2 ห้อง และผู้ใช้ที่ไม่ได้เข้าสู่ระบบ 1 ห้อง"""
    llm(*[AIMessage("ตอบ")] * 3)
    path = str(tmp_path / "aura.sqlite")
    async with sqlite_checkpointer(path) as saver:
        graph = build_graph(saver)
        for user_id, thread_id, jwt in [
            (119231, "t1", JWT),
            (119231, "t2", JWT),
            ("anonymous", ANON_THREAD, None),
        ]:
            config = run_config(user_id=user_id, thread_id=thread_id, jwt=jwt)
            await graph.ainvoke({"messages": [HumanMessage("ถาม")]}, config)
    return path


async def remaining(path: str) -> list[str]:
    async with (
        sqlite_checkpointer(path) as saver,
        saver.conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY 1") as cur,
    ):
        return [row[0] for row in await cur.fetchall()]


async def prune(path: str, *, after: timedelta, dry_run: bool = False):
    async with sqlite_checkpointer(path) as saver:
        return await prune_threads(
            saver,
            now=datetime.now(UTC) + after,
            max_age=DAYS_30,
            anonymous_max_age=DAY_1,
            dry_run=dry_run,
        )


async def test_recent_threads_are_kept(chat_db):
    result = await prune(chat_db, after=timedelta(hours=1))

    assert (result.checked, result.deleted) == (3, 0)
    assert len(await remaining(chat_db)) == 3


async def test_anonymous_threads_expire_first(chat_db):
    result = await prune(chat_db, after=timedelta(days=2))

    assert (result.deleted, result.deleted_anonymous) == (1, 1)
    assert await remaining(chat_db) == ["119231:t1", "119231:t2"]


async def test_old_threads_of_everyone_are_deleted(chat_db):
    result = await prune(chat_db, after=timedelta(days=31))

    assert (result.checked, result.deleted, result.deleted_anonymous) == (3, 3, 1)
    assert await remaining(chat_db) == []
    async with (
        sqlite_checkpointer(chat_db) as saver,
        saver.conn.execute("SELECT COUNT(*) FROM writes") as cur,
    ):
        assert (await cur.fetchone())[0] == 0


async def test_dry_run_counts_without_deleting(chat_db):
    result = await prune(chat_db, after=timedelta(days=31), dry_run=True)

    assert result.deleted == 3
    assert len(await remaining(chat_db)) == 3


async def test_empty_database(tmp_path):
    result = await prune(str(tmp_path / "new.sqlite"), after=timedelta(days=31))

    assert (result.checked, result.deleted) == (0, 0)


# ---- scripts/prune_threads.py ----


def load_script():
    spec = importlib.util.spec_from_file_location("prune_threads_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_script_dry_run_prints_counts_only(chat_db, capsys):
    script = load_script()

    code = await script.main(["--sqlite-path", chat_db, "--dry-run"])

    out = capsys.readouterr().out
    assert code == 0
    assert "ตรวจ 3 ห้อง" in out
    assert "119231" not in out and ANON_THREAD not in out  # ไม่พิมพ์ thread_id
    assert len(await remaining(chat_db)) == 3


@pytest.mark.parametrize("args", [["--days", "0"], ["--anonymous-days", "-1"]])
def test_script_rejects_non_positive_days(args):
    with pytest.raises(SystemExit):
        load_script().parse_args(args)
