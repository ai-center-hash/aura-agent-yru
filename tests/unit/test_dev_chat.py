"""test ของหน้าแชททดสอบ (scripts/dev_chat.py) โดยเฉพาะการ login ด้วย YRU Passport

ไม่ต่อ Passport จริง — mock token endpoint และ userinfo ด้วย respx
"""

import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

SCRIPTS = Path(__file__).parents[2] / "scripts"
PASSPORT = "https://passport.test"
SECRET = "test-client-secret-xyz"
ACCESS_TOKEN = "passport.user.access-token"

STUDENT_INFO = {
    "sub": 10001,
    "username": "406500001",
    "user_type": "student",
    "display_name": "นักศึกษาทดสอบ ระบบ",
    "org_unit_1_name": "คณะวิทยาศาสตร์และเทคโนโลยี",
}


def load_script(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # @dataclass ต้องหา module ของตัวเองเจอใน sys.modules
    spec.loader.exec_module(module)
    return module


dev_chat = load_script("dev_chat")
passport_oauth = load_script("passport_oauth")


@pytest.fixture
def passport_env(monkeypatch, settings_env):
    """ให้ ActClient ตัวจริงของหน้าแชทคุยกับ Passport ปลอม"""
    from aura_agent.config import get_settings

    monkeypatch.setenv("PASSPORT_BASE_URL", PASSPORT)
    monkeypatch.setenv("IDENTITY_MODE", "passport")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def web(passport_env):
    oauth = passport_oauth.OAuthClient(
        base_url=PASSPORT,
        client_id="269",
        client_secret=SECRET,
        redirect_uri="http://127.0.0.1/callback",
    )
    app = dev_chat.create_app(oauth=oauth)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        client.app = app
        yield client
    if app.state.real_client is not None:
        await app.state.real_client.aclose()


def mock_passport(respx_mock, userinfo=None):
    token_route = respx_mock.post(f"{PASSPORT}/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": ACCESS_TOKEN, "token_type": "Bearer"}
        )
    )
    respx_mock.get(f"{PASSPORT}/oidc/userinfo").mock(
        return_value=httpx.Response(200, json=userinfo or STUDENT_INFO)
    )
    return token_route


async def start_login(web) -> str:
    response = await web.get("/auth/login")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


# ---- เริ่ม login ----


async def test_login_redirects_to_passport(web):
    response = await web.get("/auth/login")

    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert response.status_code == 302
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{PASSPORT}/oauth/authorize"
    assert query["client_id"] == ["269"]
    assert query["redirect_uri"] == ["http://127.0.0.1/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email"]
    assert len(query["state"][0]) >= 24
    assert SECRET not in response.headers["location"]  # secret ห้ามออกไปที่เบราว์เซอร์


async def test_each_login_gets_a_new_state(web):
    assert await start_login(web) != await start_login(web)


# ---- callback ----


async def test_callback_creates_session(web, respx_mock):
    token_route = mock_passport(respx_mock)
    state = await start_login(web)

    response = await web.get("/callback", params={"code": "abc", "state": state})

    assert response.status_code == 302
    assert response.headers["location"] == "/?mode=passport&login=ok"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{dev_chat.SESSION_COOKIE}=")
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert ACCESS_TOKEN not in cookie  # cookie เก็บแค่ session id ไม่ใช่ token

    sent = parse_qs(token_route.calls.last.request.content.decode())
    assert sent["code"] == ["abc"]
    assert sent["client_secret"] == [SECRET]  # ส่ง secret จากฝั่ง server
    assert sent["redirect_uri"] == ["http://127.0.0.1/callback"]


async def test_me_shows_who_is_logged_in_without_the_token(web, respx_mock):
    mock_passport(respx_mock)
    state = await start_login(web)
    await web.get("/callback", params={"code": "abc", "state": state})

    me = (await web.get("/api/me")).json()

    assert me == {
        "logged_in": True,
        "name": "นักศึกษาทดสอบ ระบบ",
        "faculty": "คณะวิทยาศาสตร์และเทคโนโลยี",
    }
    assert ACCESS_TOKEN not in str(me)


async def test_callback_rejects_unknown_state(web, respx_mock):
    token_route = mock_passport(respx_mock)

    response = await web.get("/callback", params={"code": "abc", "state": "ปลอม"})

    assert response.status_code == 400
    assert not token_route.called  # ไม่แลก code ถ้า state ไม่ถูก


async def test_state_is_single_use(web, respx_mock):
    mock_passport(respx_mock)
    state = await start_login(web)
    await web.get("/callback", params={"code": "abc", "state": state})

    replay = await web.get("/callback", params={"code": "abc", "state": state})

    assert replay.status_code == 400


async def test_expired_state_is_rejected(web, respx_mock, monkeypatch):
    mock_passport(respx_mock)
    state = await start_login(web)
    web.app.state.pending_states[state] -= dev_chat.STATE_TTL_S + 1

    response = await web.get("/callback", params={"code": "abc", "state": state})

    assert response.status_code == 400


async def test_staff_account_cannot_log_in(web, respx_mock):
    mock_passport(respx_mock, userinfo={**STUDENT_INFO, "user_type": "staff"})
    state = await start_login(web)

    response = await web.get("/callback", params={"code": "abc", "state": state})

    assert response.headers["location"] == "/?mode=passport&login=not_student"
    assert "set-cookie" not in response.headers
    assert web.app.state.sessions == {}


async def test_user_cancelled_on_passport(web):
    response = await web.get("/callback", params={"error": "access_denied", "state": "x"})

    assert response.headers["location"] == "/?mode=passport&login=cancelled"


async def test_token_exchange_failure(web, respx_mock):
    respx_mock.post(f"{PASSPORT}/oauth/token").mock(return_value=httpx.Response(400))
    state = await start_login(web)

    response = await web.get("/callback", params={"code": "เก่า", "state": state})

    assert response.headers["location"] == "/?mode=passport&login=error"
    assert web.app.state.sessions == {}


# ---- ใช้ session คุย และออกจากระบบ ----


async def test_passport_chat_requires_login(web):
    response = await web.post(
        "/api/chat", json={"thread_id": "t", "message": "สวัสดี", "mode": "passport"}
    )

    assert response.status_code == 401


async def test_logout_removes_session(web, respx_mock):
    mock_passport(respx_mock)
    state = await start_login(web)
    await web.get("/callback", params={"code": "abc", "state": state})

    await web.post("/auth/logout")

    assert (await web.get("/api/me")).json() == {"logged_in": False}
    assert web.app.state.sessions == {}


async def test_expired_session_is_dropped(web, respx_mock):
    mock_passport(respx_mock)
    state = await start_login(web)
    await web.get("/callback", params={"code": "abc", "state": state})
    session = next(iter(web.app.state.sessions.values()))
    session.created_at -= dev_chat.SESSION_TTL_S + 1

    assert (await web.get("/api/me")).json() == {"logged_in": False}


# ---- เมื่อยังไม่ได้ตั้งค่า client ----


async def test_login_unavailable_without_client_credentials(passport_env):
    app = dev_chat.create_app(oauth=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        info = (await client.get("/api/info")).json()
        login = await client.get("/auth/login")

    assert info["login_available"] is False
    assert login.status_code == 503


async def test_info_never_exposes_the_secret(web):
    body = (await web.get("/api/info")).text + (await web.get("/")).text

    assert SECRET not in body


# ---- ตัวช่วย OAuth ----


def test_default_redirect_uri_matches_registration():
    assert passport_oauth.default_redirect_uri(80) == "http://127.0.0.1/callback"
    assert passport_oauth.default_redirect_uri(8100) == "http://127.0.0.1:8100/callback"


def test_oauth_client_from_settings_requires_both_values():
    from aura_agent.config import Settings

    base = {"_env_file": None, "service_key": "x" * 32}

    assert passport_oauth.oauth_client_from(Settings(**base)) is None
    assert passport_oauth.oauth_client_from(Settings(**base, passport_client_id="269")) is None
    client = passport_oauth.oauth_client_from(
        Settings(**base, passport_client_id="269", passport_client_secret=SECRET)
    )
    assert client.client_secret == SECRET
    assert client.redirect_uri == "http://127.0.0.1/callback"
