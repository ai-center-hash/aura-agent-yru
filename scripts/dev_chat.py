"""หน้าแชทสำหรับทดลองเล่นในเครื่องตัวเอง (ไม่ใช่ของ production)

    ssh -N -L 11434:localhost:11434 yruadmin@10.20.41.54     # tunnel ไป Ollama ก่อน
    python -m uv run python scripts/dev_chat.py              # แล้วเปิด http://127.0.0.1

มี 2 โหมด
- **persona จำลอง** ใช้ข้อมูลใน tests/evals/personas/ ไม่ต้อง login และไม่แตะข้อมูลจริง
- **บัญชี YRU Passport** กด "เข้าสู่ระบบ" แล้ว login ด้วย Passport จริง คุยกับข้อมูลจริงของตัวเอง

การ login (Authorization Code flow)
- ต้องตั้ง `PASSPORT_CLIENT_ID` / `PASSPORT_CLIENT_SECRET` ใน .env
- callback ที่ลงทะเบียนไว้กับ Passport คือ `http://127.0.0.1/callback` จึงเปิดที่ port 80 เป็นค่าเริ่มต้น
  (ใช้ port อื่นต้องเพิ่ม callback URL นั้นใน Passport ก่อน หรือตั้ง `PASSPORT_REDIRECT_URI`)
- server เป็นคนแลก code เป็น token และเก็บ token ไว้ฝั่ง server · เบราว์เซอร์ได้แค่ cookie แบบ HttpOnly

หมายเหตุ
- เปิดเฉพาะ 127.0.0.1 และไม่มีการตรวจ service key — **อย่าเอาไป deploy** ของจริงอยู่ที่ `aura_agent.api.main`
- ตั้งใจให้ใช้คนเดียว (สลับ ActClient ต่อ request) ถ้าคุยพร้อมกันหลายแท็บข้อมูลอาจสลับกันได้
- ประวัติแชทและ session เก็บในหน่วยความจำ ปิดเซิร์ฟเวอร์แล้วหาย
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # รันเป็น script: ให้ import tests.evals.* และสคริปต์ข้างเคียงได้
    sys.path.insert(0, str(Path(__file__).parents[1]))
    sys.path.insert(0, str(Path(__file__).parent))

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from langgraph.checkpoint.memory import InMemorySaver
from passport_oauth import OAuthClient, oauth_client_from
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from aura_agent import clock
from aura_agent.agent import build_graph, state_serializer
from aura_agent.api.schemas import MAX_MESSAGE_LEN
from aura_agent.api.sse import chat_events
from aura_agent.config import get_settings
from aura_agent.data import ActApiError, ActClient, NotAStudent, build_act_client, set_act_client
from aura_agent.processing import analyze_gaps
from tests.evals.personas import (
    EVAL_JWT,
    EVAL_TODAY,
    PersonaClient,
    available_personas,
    load_persona,
)

logger = logging.getLogger("dev_chat")

PAGE = Path(__file__).parent / "dev_chat.html"
DEFAULT_PORT = 80

SESSION_COOKIE = "aura_dev_session"
SESSION_TTL_S = 8 * 3600
STATE_TTL_S = 600  # ต้อง login ให้เสร็จภายใน 10 นาทีหลังกดปุ่ม

# เรียงตามนี้ในหน้าเว็บ (ตัวแรกเป็นค่าเริ่มต้น) ไม่ใช่เรียงตามชื่อโฟลเดอร์
PERSONA_LABELS = {
    "normal_with_gaps": "นักศึกษาปกติ · ยังขาด 2 หมวด",
    "transfer_with_gaps": "นักศึกษาเทียบโอน · ยังขาด 2 หมวด",
    "completed_all": "นักศึกษาปกติ · ครบตามเกณฑ์แล้ว",
    "realistic_with_gaps": "โครงสร้างกรอบจริง 2566 · ยังขาด 5 หมวด",
}

SUGGESTIONS = [
    "ผมยังขาดกิจกรรมหมวดไหนบ้าง",
    "มีกิจกรรมอะไรเปิดรับสมัครอยู่บ้าง",
    "แนะนำกิจกรรมให้ครบหน่อย",
    "ผมลงทะเบียนกิจกรรมอะไรไว้บ้าง",
    "มีกิจกรรมจิตอาสาไหม",
    "ลงทะเบียนกิจกรรมจิตอาสาให้ผมหน่อย",
]


@dataclass
class LoginSession:
    """ผู้ใช้ที่ login แล้ว — token อยู่ตรงนี้ฝั่ง server เท่านั้น"""

    token: str
    name: str
    faculty: str | None
    created_at: float

    def expired(self, now: float) -> bool:
        return now - self.created_at > SESSION_TTL_S


class DevChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)
    mode: str = "persona"
    persona: str = "normal_with_gaps"


def ordered_personas() -> list[str]:
    found = available_personas()
    known = [name for name in PERSONA_LABELS if name in found]
    return known + [name for name in found if name not in PERSONA_LABELS]


def persona_card(name: str) -> dict[str, Any]:
    """ข้อมูลว่า persona นี้คือนักศึกษาคนไหน เอาไปแสดงบนหน้าเว็บให้รู้ว่ากำลังคุยในฐานะใคร"""
    persona = load_persona(name)
    user = persona.summary.user
    report = analyze_gaps(persona.summary)
    return {
        "name": name,
        "label": PERSONA_LABELS.get(name, name),
        "student_name": user.name,
        "student_id": user.student_id,
        "faculty": user.faculty,
        "major": user.major,
        "status": "เทียบโอน" if user.student_status == "transfer" else "ปกติ",
        "progress": f"{report.total_activities} กิจกรรม {report.total_hours:g} ชม.",
        "gaps": [gap.category_name for gap in report.gaps],
        "registrations": len(persona.registrations),
    }


def create_app(*, oauth: OAuthClient | None) -> FastAPI:
    app = FastAPI(title="AURA dev chat", docs_url=None, redoc_url=None)
    app.state.graph = build_graph(InMemorySaver(serde=state_serializer()))
    app.state.real_client = None
    app.state.oauth = oauth
    app.state.sessions = {}  # session id → LoginSession
    app.state.pending_states = {}  # OAuth state → เวลาที่สร้าง

    @app.get("/")
    async def page() -> FileResponse:
        # no-store เพื่อให้แก้ไฟล์ HTML แล้วรีเฟรชเห็นผลทันที
        return FileResponse(
            PAGE, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        settings = get_settings()
        return {
            "model": settings.llm_model,
            "act_api_base_url": settings.act_api_base_url,
            "fixture_date": EVAL_TODAY.isoformat(),  # โหมด persona ใช้วันนี้เสมอ
            "today": date.today().isoformat(),  # โหมด Passport ใช้วันจริง
            "login_available": app.state.oauth is not None,
            "suggestions": SUGGESTIONS,
            "personas": [persona_card(name) for name in ordered_personas()],
        }

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, Any]:
        session = _session_of(app, request)
        if session is None:
            return {"logged_in": False}
        return {"logged_in": True, "name": session.name, "faculty": session.faculty}

    # ---- login ด้วย YRU Passport ----

    @app.get("/auth/login")
    async def login() -> RedirectResponse:
        oauth_client = _require_oauth(app)
        state = secrets.token_urlsafe(24)
        _forget_old_states(app)
        app.state.pending_states[state] = time.time()
        return RedirectResponse(oauth_client.authorize_url(state), status_code=302)

    @app.get("/callback")
    async def callback(
        request: Request, code: str = "", state: str = "", error: str = ""
    ) -> RedirectResponse:
        oauth_client = _require_oauth(app)
        if error:
            return _back("cancelled" if error == "access_denied" else "error")

        created = app.state.pending_states.pop(state, None)
        if not state or created is None or time.time() - created > STATE_TTL_S:
            raise HTTPException(400, "คำขอ login หมดอายุหรือไม่ถูกต้อง กลับไปกดเข้าสู่ระบบใหม่")
        if not code:
            return _back("error")

        try:
            tokens = await oauth_client.exchange_code(code)
            token = str(tokens["access_token"])
            identity = await _real_client(app).get_identity(token)
        except NotAStudent:
            return _back("not_student")
        except (httpx.HTTPError, KeyError, ActApiError) as error_:
            logger.warning("passport login failed error=%s", type(error_).__name__)
            return _back("error")

        session_id = secrets.token_urlsafe(32)
        app.state.sessions[session_id] = LoginSession(
            token=token,
            name=identity.display if identity is not None else "ไม่ทราบชื่อ",
            faculty=identity.org_unit_1_name if identity is not None else None,
            created_at=time.time(),
        )
        response = _back("ok")
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_TTL_S,
            httponly=True,  # JavaScript อ่าน cookie นี้ไม่ได้
            samesite="lax",  # ส่ง cookie ตอนถูก redirect กลับจาก Passport ได้ แต่ไม่ส่งกับ POST ข้ามเว็บ
            path="/",
        )
        return response

    @app.post("/auth/logout")
    async def logout(request: Request) -> dict[str, bool]:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            app.state.sessions.pop(session_id, None)
        return {"ok": True}

    # ---- แชท ----

    @app.post("/api/chat")
    async def chat(payload: DevChatRequest, request: Request) -> EventSourceResponse:
        if payload.mode == "persona":
            if payload.persona not in available_personas():
                raise HTTPException(400, f"ไม่รู้จัก persona: {payload.persona}")
            client: Any = PersonaClient(load_persona(payload.persona))
            jwt = EVAL_JWT
            pinned = True  # ข้อมูลจำลองต้องใช้วันอ้างอิงของมันเสมอ
        elif payload.mode == "passport":
            session = _session_of(app, request)
            if session is None:
                raise HTTPException(401, "ยังไม่ได้เข้าสู่ระบบด้วย YRU Passport")
            client = _real_client(app)
            jwt = session.token
            pinned = False  # ข้อมูลจริงต้องใช้วันจริง
        else:
            raise HTTPException(400, f"ไม่รู้จักโหมด: {payload.mode}")

        return EventSourceResponse(
            _stream(
                app,
                client,
                pinned,
                thread_id=payload.thread_id,
                message=payload.message,
                jwt=jwt,
            )
        )

    return app


def _require_oauth(app: FastAPI) -> OAuthClient:
    if app.state.oauth is None:
        raise HTTPException(
            503, "ยังไม่ได้ตั้ง PASSPORT_CLIENT_ID / PASSPORT_CLIENT_SECRET ใน .env จึง login ไม่ได้"
        )
    return app.state.oauth


def _session_of(app: FastAPI, request: Request) -> LoginSession | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    session = app.state.sessions.get(session_id) if session_id else None
    if session is not None and session.expired(time.time()):
        app.state.sessions.pop(session_id, None)
        return None
    return session


def _forget_old_states(app: FastAPI) -> None:
    now = time.time()
    for state, created in list(app.state.pending_states.items()):
        if now - created > STATE_TTL_S:
            app.state.pending_states.pop(state, None)


def _back(result: str) -> RedirectResponse:
    """กลับไปหน้าแชทพร้อมบอกผลการ login (หน้าเว็บอ่านจาก query แล้วลบทิ้ง)"""
    return RedirectResponse(f"/?mode=passport&login={result}", status_code=302)


def _real_client(app: FastAPI) -> ActClient:
    """ActClient ตัวจริง สร้างครั้งเดียวและใช้ซ้ำ (ตาม IDENTITY_MODE เหมือน API จริง)"""
    if app.state.real_client is None:
        app.state.real_client = build_act_client()
    return app.state.real_client


@asynccontextmanager
async def _reference_date(pinned: bool) -> AsyncIterator[None]:
    """ตรึง "วันนี้" ให้ตรงกับวันอ้างอิงของ fixture ระหว่างคุยกับ persona"""
    if not pinned:
        yield
        return

    original = clock.today
    clock.today = lambda: EVAL_TODAY
    try:
        yield
    finally:
        clock.today = original


async def _stream(
    app: FastAPI, client: Any, pinned: bool, *, thread_id: str, message: str, jwt: str
) -> AsyncIterator[dict[str, str]]:
    async with _reference_date(pinned):
        set_act_client(client)
        async for event in chat_events(
            app.state.graph, thread_id=thread_id, message=message, jwt=jwt
        ):
            yield event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # กัน console บน Windows แสดงภาษาไทยเพี้ยน

    logging.basicConfig(level="INFO")
    settings = get_settings()
    oauth = oauth_client_from(settings, port=args.port)
    base = "http://127.0.0.1" + ("" if args.port == 80 else f":{args.port}")

    print(f"โมเดล: {settings.llm_model} · Ollama: {settings.ollama_base_url}")
    print(f"เปิดหน้าแชทที่ {base}/")
    if oauth is None:
        print("login ด้วย Passport: ปิดอยู่ (ยังไม่ได้ตั้ง PASSPORT_CLIENT_ID/SECRET ใน .env)")
    else:
        print(f"login ด้วย Passport: เปิด · callback = {oauth.redirect_uri}")
        if args.port != 80 and not settings.passport_redirect_uri:
            print("  ⚠ port ไม่ใช่ 80 — ต้องเพิ่ม callback URL ข้างบนในแอปบน Passport ก่อน")

    uvicorn.run(create_app(oauth=oauth), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
