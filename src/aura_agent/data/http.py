"""แกนกลางของการเรียก HTTP แบบ JSON ที่ `ActClient` และ `PassportClient` ใช้ร่วมกัน

- ยิงใหม่ 1 ครั้งเฉพาะ timeout/5xx ส่วน 4xx ไม่ยิงใหม่ (ยิงอีกก็ได้ผลเดิม)
- 401 → `TokenExpired` · 4xx อื่น → `UpstreamRejected` · ยิงไม่สำเร็จ → `unavailable_error`
- log แค่ `label` (เส้นทางแบบ template ที่ไม่มีรหัสนักศึกษา) สถานะ และเวลา
  **ไม่ log token, params หรือข้อมูลที่ได้กลับมา**
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from .errors import TokenExpired, UpstreamRejected, UpstreamSchemaError, UpstreamUnavailable

logger = logging.getLogger(__name__)

# httpx log URL เต็มที่ระดับ INFO ซึ่งมีรหัสนักศึกษา (`/summary/user/{รหัส}`), user_id
# และคำค้นที่ผู้ใช้พิมพ์ ปิดไว้ที่ WARNING เพื่อให้ log ของเราเป็นที่เดียวที่บันทึก request
# (ถ้าต้อง debug ให้ลดระดับเองชั่วคราว)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

MAX_ATTEMPTS = 2  # ยิงครั้งแรก + ยิงใหม่ได้ 1 ครั้ง


class JsonApi:
    """client ฐานที่ถือ `httpx.AsyncClient` ตัวเดียวตลอดอายุของ instance"""

    service_name = "api"
    unavailable_error: type[UpstreamUnavailable] = UpstreamUnavailable

    def __init__(self, base_url: str, timeout_s: float, *, retry_delay_s: float = 0.25) -> None:
        self._retry_delay_s = retry_delay_s
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "JsonApi":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def _fetch(
        self, path: str, params: dict[str, str], *, auth: str | None, label: str
    ) -> Any:
        reason = "ไม่ทราบสาเหตุ"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._request(path, params, auth=auth, label=label)
            except httpx.TransportError as exc:
                reason = type(exc).__name__
            else:
                if response.status_code < 400:
                    return self._json_of(response, label)
                if response.status_code == 401:
                    raise TokenExpired(f"{label}: HTTP 401")
                if response.status_code < 500:
                    raise UpstreamRejected(f"{label}: HTTP {response.status_code}")
                reason = f"HTTP {response.status_code}"

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(self._retry_delay_s)

        raise self.unavailable_error(f"{label}: {reason} (ยิงแล้ว {MAX_ATTEMPTS} ครั้ง)")

    async def _request(
        self, path: str, params: dict[str, str], *, auth: str | None, label: str
    ) -> httpx.Response:
        """ยิง 1 ครั้ง ส่ง `Authorization` เฉพาะเมื่อมี `auth`"""
        headers = {"Authorization": f"Bearer {auth}"} if auth else {}
        started = time.perf_counter()
        try:
            response = await self._client.get(path, params=params, headers=headers)
        except httpx.TransportError as exc:
            logger.warning(
                "%s path=%s error=%s ms=%.0f",
                self.service_name,
                label,
                type(exc).__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "%s path=%s status=%d ms=%.0f",
            self.service_name,
            label,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @staticmethod
    def _json_of(response: httpx.Response, label: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamSchemaError(f"{label}: response ไม่ใช่ JSON") from exc
