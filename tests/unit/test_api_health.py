"""test ของ `GET /v1/health` (mock Ollama ด้วย respx, Activity API ใช้ client ปลอม)"""

import asyncio

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from aura_agent.api.main import create_app
from aura_agent.api.routes import health as health_module
from aura_agent.data import UpstreamUnavailable

from .conftest import OLLAMA_URL

TAGS_URL = f"{OLLAMA_URL}/api/tags"
MODEL = "qwen3.6:35b-a3b"


@pytest.fixture
async def health_client(settings_env, act_client):
    app = create_app(graph=object())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://aura.test") as client:
        yield client


def tags(*models: str) -> dict:
    return {"models": [{"model": name} for name in models]}


async def test_health_ok(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags(MODEL, "llama3")))

    response = await health_client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ollama": "ok", "activity_api": "ok"}


async def test_health_needs_no_service_key(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags(MODEL)))

    assert (await health_client.get("/v1/health")).status_code == 200


async def test_health_reports_missing_model(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags("llama3")))

    body = (await health_client.get("/v1/health")).json()

    assert body["ollama"] == "model_missing"
    assert body["status"] == "degraded"


async def test_health_when_ollama_is_unreachable(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(side_effect=httpx.ConnectError("tunnel ปิด"))

    body = (await health_client.get("/v1/health")).json()

    assert body["ollama"] == "down"
    assert body["status"] == "degraded"
    assert body["activity_api"] == "ok"


async def test_health_when_ollama_returns_error(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(500))

    assert (await health_client.get("/v1/health")).json()["ollama"] == "down"


async def test_health_when_ollama_returns_garbage(health_client, respx_mock):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))

    assert (await health_client.get("/v1/health")).json()["ollama"] == "down"


async def test_health_when_activity_api_is_down(health_client, respx_mock, act_client):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags(MODEL)))

    async def ping() -> bool:
        return False

    act_client.ping = ping

    body = (await health_client.get("/v1/health")).json()

    assert body["activity_api"] == "down"
    assert body["status"] == "degraded"


async def test_health_when_activity_api_raises(health_client, respx_mock, act_client):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags(MODEL)))

    async def ping() -> bool:
        raise UpstreamUnavailable("timeout")

    act_client.ping = ping

    assert (await health_client.get("/v1/health")).json()["activity_api"] == "down"


async def test_health_times_out_slow_activity_api(
    health_client, respx_mock, act_client, monkeypatch
):
    respx_mock.get(TAGS_URL).mock(return_value=httpx.Response(200, json=tags(MODEL)))
    monkeypatch.setattr(health_module, "HEALTH_TIMEOUT_S", 0.01)

    async def ping() -> bool:
        await asyncio.sleep(1)
        return True

    act_client.ping = ping

    assert (await health_client.get("/v1/health")).json()["activity_api"] == "down"


async def test_health_skips_llm_check_for_other_providers(settings_env, act_client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu:8000/v1")
    from aura_agent.config import get_settings

    get_settings.cache_clear()

    app = create_app(graph=object())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://aura.test") as client:
        body = (await client.get("/v1/health")).json()

    assert body["ollama"] == "unknown"
    assert body["status"] == "degraded"
