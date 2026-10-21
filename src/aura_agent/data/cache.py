"""TTL cache ของชั้น data

key = (path, params, fingerprint ของ JWT) — **ห้ามใช้ JWT ดิบเป็น key**
เพราะ key อาจถูก log หรือถูกย้ายไปอยู่ Redis ในภายหลัง
interface เป็น async เพื่อให้เปลี่ยนไปใช้ Redis ได้โดยไม่ต้องแก้ ActClient
"""

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from cachetools import TLRUCache

FINGERPRINT_LEN = 16


def jwt_fingerprint(jwt: str) -> str:
    """ย่อ JWT เป็น hash สั้นๆ สำหรับแยก cache ของผู้ใช้แต่ละคน"""
    return hashlib.sha256(jwt.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


def make_cache_key(path: str, params: Mapping[str, str], jwt: str) -> str:
    """สร้าง key ที่คงที่ไม่ขึ้นกับลำดับของ params"""
    query = urlencode(sorted(params.items()))
    return f"{path}?{query}|{jwt_fingerprint(jwt)}"


class Cache(Protocol):
    """interface ที่ ActClient ต้องการ (Phase 2 ทำ RedisCache ให้ตรงนี้ได้)"""

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_s: float) -> None: ...


@dataclass(slots=True)
class _Entry:
    value: Any
    ttl_s: float


def _time_to_use(_key: str, entry: _Entry, now: float) -> float:
    """TLRUCache เรียกเพื่อถามว่า entry นี้หมดอายุเมื่อไร (ทำให้ตั้ง TTL ต่อ key ได้)"""
    return now + entry.ttl_s


class MemoryCache:
    """cache ในหน่วยความจำของ process เดียว ตั้ง TTL แยกต่อ key ได้"""

    def __init__(self, maxsize: int = 512, timer: Callable[[], float] = time.monotonic) -> None:
        self._cache: TLRUCache[str, _Entry] = TLRUCache(
            maxsize=maxsize, ttu=_time_to_use, timer=timer
        )

    async def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        return None if entry is None else entry.value

    async def set(self, key: str, value: Any, ttl_s: float) -> None:
        self._cache[key] = _Entry(value, ttl_s)

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


class NullCache:
    """ไม่ cache อะไรเลย ใช้ตอนทดสอบกับ API จริงหรือตอน debug"""

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl_s: float) -> None:
        return None
