"""แชททดสอบใน terminal

    $env:AURA_DEV_JWT="<JWT ของตัวเอง>"
    python -m uv run python -m aura_agent.cli

รับ JWT จาก environment เท่านั้น (ไม่รับเป็น argument จะได้ไม่ค้างใน shell history)
คำสั่ง: `/new` เริ่มห้องแชทใหม่ · `/quit` ออก
"""

import asyncio
import sys
import time
import uuid
from os import environ
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from .agent import build_graph, run_config, sqlite_checkpointer
from .config import get_settings
from .data import ActApiError, NoActivityFrame, close_act_client, get_act_client
from .tools import TOOL_STATUS

PROMPT = "\nคุณ > "
NO_JWT_MESSAGE = (
    "ไม่พบ AURA_DEV_JWT ใน environment\n"
    '  PowerShell: $env:AURA_DEV_JWT="<JWT ของตัวเอง>"\n'
    "  bash:       export AURA_DEV_JWT=<JWT ของตัวเอง>"
)


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # กัน console บน Windows แสดงภาษาไทยเพี้ยน

    jwt = environ.get("AURA_DEV_JWT", "").strip()
    if not jwt:
        print(NO_JWT_MESSAGE)
        return 2

    settings = get_settings()
    client = get_act_client()
    try:
        subject = await client.get_subject(jwt)
        who = await describe_student(client, jwt)
    except ActApiError as error:
        print(f"ยืนยันตัวตนไม่ได้: {error.code} · {error.message_th}")
        await close_act_client()
        return 1

    print(f"คุยกับ AURA ได้เลยครับ (โมเดล {settings.llm_model}) · /new เริ่มใหม่ · /quit ออก")
    print(f"นักศึกษา: {who}")

    try:
        async with sqlite_checkpointer(settings.sqlite_path) as checkpointer:
            graph = build_graph(checkpointer)
            thread_id = str(uuid.uuid4())

            while True:
                message = (await asyncio.to_thread(input, PROMPT)).strip()
                if not message:
                    continue
                if message == "/quit":
                    break
                if message == "/new":
                    thread_id = str(uuid.uuid4())
                    print("เริ่มห้องแชทใหม่แล้วครับ")
                    continue
                await ask(graph, message, user_id=subject, thread_id=thread_id, jwt=jwt)
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        await close_act_client()

    return 0


async def describe_student(client: Any, jwt: str) -> str:
    """บรรทัดบอกว่ากำลังคุยในฐานะใคร (ยังไม่มีกรอบกิจกรรมก็บอกได้จาก Passport)"""
    try:
        summary = await client.get_my_summary(jwt)
    except NoActivityFrame as missing:
        identity = missing.identity
        name = identity.display if identity is not None else "ไม่ทราบชื่อ"
        faculty = identity.org_unit_1_name if identity is not None else "-"
        return f"{name} · {faculty} · ยังไม่มีกรอบกิจกรรม ({missing.detail or 'no_frame'})"
    return f"{summary.user.name} · {summary.user.faculty}"


async def ask(graph: Any, message: str, *, user_id: int | str, thread_id: str, jwt: str) -> None:
    """ถาม 1 คำถาม แล้วแสดงชื่อ tool ที่เรียก คำตอบแบบ stream และเวลาที่ใช้"""
    started = time.perf_counter()
    config = run_config(user_id=user_id, thread_id=thread_id, jwt=jwt)

    print("AURA > ", end="", flush=True)
    try:
        async for mode, payload in graph.astream(
            {"messages": [HumanMessage(message)]}, config, stream_mode=["updates", "messages"]
        ):
            if mode == "updates":
                _print_tool_status(payload)
            else:
                chunk, metadata = payload
                if metadata.get("langgraph_node") == "agent":
                    print(chunk_text(chunk), end="", flush=True)
    except ActApiError as error:
        print(f"\n[{error.code}] {error.message_th}")
    except Exception as error:  # noqa: BLE001 - CLI ทดสอบ ขอให้เห็น error ทุกแบบ
        print(f"\n[ERROR] {type(error).__name__}: {error}")

    print(f"\n({(time.perf_counter() - started) * 1000:.0f} ms)")


def _print_tool_status(updates: dict[str, Any]) -> None:
    for node, update in updates.items():
        if node != "agent" or not isinstance(update, dict):
            continue
        for message in update.get("messages", []):
            for call in getattr(message, "tool_calls", []) or []:
                name = call.get("name", "")
                print(f"\n[{TOOL_STATUS.get(name, name)}]")
                print("AURA > ", end="", flush=True)


def chunk_text(chunk: Any) -> str:
    """ดึงข้อความจาก message chunk (langchain คืน content เป็น string หรือ list ของ block)"""
    if isinstance(chunk, AIMessage) and getattr(chunk, "tool_calls", None):
        return ""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
