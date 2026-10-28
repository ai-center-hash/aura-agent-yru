"""`GET /v1/health` — ไม่ต้องใช้ JWT และไม่ต้องใช้ service key (ให้ระบบ monitoring เรียกได้)

ใครก็เรียกได้ จึงจำผลไว้ `HEALTH_CACHE_S` วินาที ไม่ให้การยิงถี่ๆ กลายเป็นการยิง Ollama/Activity API ตาม
"""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter

from ...config import Settings, get_settings
from ...data import ActApiError, get_act_client
from ..schemas import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["health"])

HEALTH_TIMEOUT_S = 3.0
HEALTH_CACHE_S = 10.0

OK = "ok"
DOWN = "down"
MODEL_MISSING = "model_missing"
UNKNOWN = "unknown"


_lock = asyncio.Lock()
_last: tuple[float, HealthResponse] | None = None


@router.get("/health")
async def health() -> HealthResponse:
    global _last
    async with _lock:  # request ที่มาพร้อมกันรอผลจากการเช็ครอบเดียวกัน
        if _last is not None and time.monotonic() - _last[0] < HEALTH_CACHE_S:
            return _last[1]
        settings = get_settings()
        llm_status, activity_status = await asyncio.gather(
            check_llm(settings), check_activity_api()
        )
        overall = OK if llm_status == OK and activity_status == OK else "degraded"
        result = HealthResponse(status=overall, ollama=llm_status, activity_api=activity_status)
        _last = (time.monotonic(), result)
        return result


def clear_health_cache() -> None:
    """ลืมผลที่จำไว้ (ใช้ใน test)"""
    global _last
    _last = None


async def check_llm(settings: Settings) -> str:
    """เช็คว่า Ollama ตอบและมีโมเดลที่ตั้งไว้จริง"""
    if settings.llm_provider != "ollama":
        return UNKNOWN  # provider อื่น (vLLM) ยังไม่ได้ทำ health check

    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S) as client:
            response = await client.get(url)
    except httpx.HTTPError as error:
        logger.warning("health ollama unreachable error=%s", type(error).__name__)
        return DOWN

    if response.status_code >= 400:
        return DOWN

    try:
        models = response.json().get("models", [])
    except ValueError:
        return DOWN

    names = {model.get("model") or model.get("name") for model in models if isinstance(model, dict)}
    return OK if settings.llm_model in names else MODEL_MISSING


async def check_activity_api() -> str:
    try:
        reachable = await asyncio.wait_for(get_act_client().ping(), timeout=HEALTH_TIMEOUT_S)
    except (TimeoutError, ActApiError) as error:
        logger.warning("health activity api down error=%s", type(error).__name__)
        return DOWN
    return OK if reachable else DOWN
