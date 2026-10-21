"""ขอ access token ของผู้ใช้จาก YRU Passport ด้วย Authorization Code flow (เครื่องมือ dev เท่านั้น)

ใช้ตอบคำถาม Q1: token ของ Passport ใช้กับ `GET /v1/report/summary/me` ของ Activity API ได้ไหม

    PASSPORT_CLIENT_ID=269 PASSPORT_CLIENT_SECRET=<secret> \
        python -m uv run python scripts/passport_login.py

ขั้นตอน: script เปิดเซิร์ฟเวอร์เล็กๆ รอ callback → พิมพ์ URL ให้เอาไปเปิดในเบราว์เซอร์ →
ล็อกอิน → Passport ส่ง code กลับมา → script แลกเป็น token แล้วทดสอบกับ Activity API ให้เลย

**ของจริงไม่ได้ใช้ไฟล์นี้** — ใน production frontend/backend เป็นฝ่ายทำ OAuth แล้วส่ง JWT ต่อให้ AURA
script นี้มีไว้เพื่อให้ผู้พัฒนาได้ token มาทดสอบ

ความปลอดภัย
- อ่าน client secret จาก .env (git ไม่เก็บ) ไม่รับจาก command line
- พิมพ์ค่า claim ที่เป็นข้อมูลส่วนบุคคลแบบปิดบัง (เช่น `40651****`)
- เก็บ access token ลง `dev.jwt` ซึ่ง `.gitignore` ครอบอยู่แล้ว (`*.jwt`)
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

if __package__ in (None, ""):  # รันเป็น script: ให้ import แพ็กเกจในโปรเจ็คและสคริปต์ข้างเคียงได้
    sys.path.insert(0, str(Path(__file__).parents[1]))
    sys.path.insert(0, str(Path(__file__).parent))

from passport_oauth import oauth_client_from  # noqa: E402

from aura_agent.config import get_settings  # noqa: E402

ISSUER = "https://passport.yru.ac.th"
USERINFO_URL = f"{ISSUER}/oidc/userinfo"

ACT_API = os.environ.get("ACT_API_BASE_URL", "https://api831.yru.ac.th/act/api")

TOKEN_FILE = Path(__file__).parents[1] / "dev.jwt"
WAIT_SECONDS = 300

PRIVATE_CLAIMS = {
    "name", "given_name", "family_name", "display_name", "email", "cid",
    "fullname_with_prefix", "fullname_with_academic_prefix", "firstname", "lastname",
    "preferred_username", "username", "sub", "avatar",
}  # fmt: skip

PAGE_OK = """<!doctype html><html lang="th"><meta charset="utf-8">
<body style="font-family:sans-serif;padding:40px">
<h2>ล็อกอินสำเร็จ</h2><p>กลับไปดูผลที่ terminal ได้เลยครับ ปิดหน้านี้ได้</p></body></html>"""


class CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - ชื่อตามที่ BaseHTTPRequestHandler กำหนด
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") not in ("/callback", ""):
            self.send_error(404)
            return

        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        CallbackHandler.result.update(params)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE_OK.encode("utf-8"))

    def log_message(self, *_args: Any) -> None:
        return  # เงียบไว้ ไม่ต้อง log ทุก request


def mask(value: Any) -> str:
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:5]}{'*' * (len(text) - 5)} ({len(text)} ตัว)"


def wait_for_code(port: int) -> dict[str, str]:
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    waited = 0
    while "code" not in CallbackHandler.result and "error" not in CallbackHandler.result:
        if waited >= WAIT_SECONDS:
            break
        threading.Event().wait(1)
        waited += 1

    server.shutdown()
    return CallbackHandler.result


def show_userinfo(access_token: str) -> None:
    print("\n[2] GET /oidc/userinfo")
    response = httpx.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30,
    )
    print(f"  HTTP {response.status_code}")
    if response.status_code >= 400:
        print("  ", response.text[:200])
        return

    claims = response.json()
    print(f"  claim ที่ได้ ({len(claims)}):")
    for key in sorted(claims):
        value = claims[key]
        shown = mask(value) if key in PRIVATE_CLAIMS else value
        print(f"    {key}: {shown}")


def check_activity_api(access_token: str) -> None:
    print(f"\n[3] GET {ACT_API}/v1/report/summary/me ด้วย token ของผู้ใช้  ← คำตอบของ Q1")
    response = httpx.get(
        f"{ACT_API}/v1/report/summary/me",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30,
    )
    print(f"  HTTP {response.status_code}")

    if response.status_code == 401:
        print("  → Activity API ไม่รับ token ของ Passport (ต้องคุยเรื่องแลก token กับเจ้าของ API)")
        print("  ", response.text[:200])
        return
    if response.status_code >= 400:
        print("  ", response.text[:300])
        return

    try:
        payload = response.json()
    except ValueError:
        print("  response ไม่ใช่ JSON:", response.text[:200])
        return

    print("  → ใช้ได้! คีย์ชั้นนอก:", sorted(payload))
    data = payload.get("data")
    if isinstance(data, dict):
        print("  คีย์ใน data:", sorted(data))
        user = data.get("user")
        if isinstance(user, dict):
            print("  คีย์ใน data.user:", sorted(user))
            print("  user.id มีค่า:", user.get("id") is not None)
            print("  student_status:", user.get("student_status"))
        summary = data.get("summary")
        if isinstance(summary, dict):
            print("  data.summary:", summary)
        categories = data.get("categories")
        if isinstance(categories, list):
            print("  จำนวน categories:", len(categories))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    oauth = oauth_client_from(get_settings())
    if oauth is None:
        print("ต้องตั้ง PASSPORT_CLIENT_ID และ PASSPORT_CLIENT_SECRET ใน .env ก่อน")
        return 2

    port = urlparse(oauth.redirect_uri).port or 80
    state = secrets.token_urlsafe(16)
    authorize = oauth.authorize_url(state)

    print("[1] เปิด URL นี้ในเบราว์เซอร์แล้วล็อกอิน (ถ้ามีบัญชีนักศึกษาทดสอบ ให้ใช้บัญชีนั้น)")
    print()
    print(authorize)
    print()
    print(f"กำลังรอ callback ที่ {oauth.redirect_uri} (รอได้ {WAIT_SECONDS} วินาที)...")
    try:
        webbrowser.open(authorize)
    except Exception:  # noqa: BLE001 - เปิดเบราว์เซอร์ไม่ได้ก็ไม่เป็นไร
        pass

    result = wait_for_code(port)
    if "error" in result:
        print("Passport ตอบ error:", result.get("error"), result.get("error_description", ""))
        return 1
    if "code" not in result:
        print("ไม่ได้รับ code (หมดเวลารอ)")
        return 1
    if result.get("state") != state:
        print("state ไม่ตรง — ยกเลิกเพื่อความปลอดภัย")
        return 1

    tokens = asyncio.run(oauth.exchange_code(result["code"]))
    access_token = tokens.get("access_token", "")
    print("\nแลก code เป็น token สำเร็จ")
    print("  token_type:", tokens.get("token_type"))
    print("  expires_in:", tokens.get("expires_in"), "วินาที")
    print("  scope:", tokens.get("scope"))
    print("  มี refresh_token:", "refresh_token" in tokens)
    print("  มี id_token:", "id_token" in tokens)
    print("  access_token:", "JWT (3 ส่วน)" if access_token.count(".") == 2 else "opaque")

    if access_token:
        TOKEN_FILE.write_text(access_token, encoding="utf-8")
        print(f"  เก็บ access token ไว้ที่ {TOKEN_FILE.name} (git ไม่เก็บไฟล์นี้)")
        show_userinfo(access_token)
        check_activity_api(access_token)

    return 0


if __name__ == "__main__":
    sys.exit(main())
