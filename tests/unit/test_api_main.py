"""test ของ lifespan — เส้นทางที่ใช้จริงตอนรัน uvicorn"""

from pathlib import Path

from aura_agent.api.main import create_app, lifespan
from aura_agent.config import get_settings
from aura_agent.data import ActClient, get_act_client


async def test_lifespan_builds_graph_and_closes_cleanly(monkeypatch, tmp_path, settings_env):
    sqlite_path = tmp_path / "data" / "aura.sqlite"
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_path))
    get_settings.cache_clear()

    app = create_app()
    assert app.state.graph is None

    async with lifespan(app):
        assert app.state.graph is not None
        assert app.state.graph.checkpointer is not None
        assert isinstance(get_act_client(), ActClient)

    assert app.state.graph is None  # ปิดแล้วต้องไม่ค้าง
    assert Path(sqlite_path).parent.is_dir()  # lifespan สร้างโฟลเดอร์ให้

    get_settings.cache_clear()


async def test_lifespan_keeps_injected_graph_and_client(act_client, settings_env):
    """ตอน test เราใส่ graph เข้ามาเอง lifespan ต้องไม่สร้าง ActClient จริงมาทับของปลอม"""
    graph = object()
    app = create_app(graph=graph)

    async with lifespan(app):
        assert app.state.graph is graph
        assert get_act_client() is act_client

    assert get_act_client() is act_client
