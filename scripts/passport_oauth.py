"""ตัวช่วย OAuth (Authorization Code flow) ของ YRU Passport — ใช้ร่วมกันระหว่างสคริปต์ dev

`dev_chat.py` และ `passport_login.py` import ไฟล์นี้ (อยู่โฟลเดอร์เดียวกัน)
ของจริงไม่ได้ใช้ไฟล์นี้: ใน production ระบบ backend เดิมเป็นคนทำ login แล้วส่ง token มาให้ AURA
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from aura_agent.config import Settings

SCOPE = "openid profile email"


@dataclass(frozen=True)
class OAuthClient:
    base_url: str
    client_id: str
    client_secret: str
    redirect_uri: str

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth/token"

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "state": state,
            }
        )
        return f"{self.authorize_endpoint}?{query}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """แลก code เป็น token (ส่ง client secret จากฝั่ง server เท่านั้น)"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
        response.raise_for_status()
        return response.json()


def default_redirect_uri(port: int) -> str:
    """ต้องตรงกับ Authorization callback URL ที่ลงทะเบียนไว้ใน Passport ทุกตัวอักษร"""
    return "http://127.0.0.1/callback" if port == 80 else f"http://127.0.0.1:{port}/callback"


def oauth_client_from(settings: Settings, *, port: int = 80) -> OAuthClient | None:
    """คืน None ถ้ายังไม่ได้ตั้ง PASSPORT_CLIENT_ID / PASSPORT_CLIENT_SECRET ใน .env"""
    if not settings.passport_client_id or settings.passport_client_secret is None:
        return None
    return OAuthClient(
        base_url=settings.passport_base_url,
        client_id=settings.passport_client_id,
        client_secret=settings.passport_client_secret.get_secret_value(),
        redirect_uri=settings.passport_redirect_uri or default_redirect_uri(port),
    )
