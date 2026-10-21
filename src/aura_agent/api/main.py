"""FastAPI app

    python -m uv run uvicorn aura_agent.api.main:app --host 0.0.0.0 --port 8000

lifespan สร้างของที่ใช้ร่วมกันครั้งเดียว: `ActClient` (httpx ตัวเดียว) → checkpointer → graph
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ..agent import build_graph, sqlite_checkpointer
from ..config import get_settings
from ..data import build_act_client, close_act_client, set_act_client
from .routes import chat, health

logger = logging.getLogger(__name__)

TITLE = "AURA-AGENT"
DESCRIPTION = "แชทบอทกิจกรรมนักศึกษา มรย. (ดู docs/01-api-contract.md)"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getattr(app.state, "graph", None) is not None:
        # มีคนใส่ graph มาให้แล้ว (ใช้ใน test) ไม่ต้องสร้างของจริง
        yield
        return

    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    client = build_act_client(settings)  # รวม PassportClient ด้วยถ้า IDENTITY_MODE=passport
    set_act_client(client)
    logger.info("aura-agent starting model=%s", settings.llm_model)

    try:
        async with sqlite_checkpointer(settings.sqlite_path) as checkpointer:
            app.state.graph = build_graph(checkpointer)
            yield
    finally:
        app.state.graph = None
        await close_act_client()
        logger.info("aura-agent stopped")


def create_app(*, graph: Any | None = None) -> FastAPI:
    """สร้าง app ใหม่ (ส่ง `graph` เข้ามาได้เพื่อใช้ของปลอมใน test)"""
    app = FastAPI(title=TITLE, description=DESCRIPTION, lifespan=lifespan)
    app.state.graph = graph
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
