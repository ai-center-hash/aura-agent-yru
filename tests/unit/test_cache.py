"""test ของ cache และ cache key (กฎสำคัญ: JWT ดิบต้องไม่โผล่ใน key)"""

from aura_agent.data import MemoryCache, NullCache, jwt_fingerprint, make_cache_key

from .conftest import JWT, OTHER_JWT


def test_cache_key_has_no_raw_jwt():
    key = make_cache_key("/v1/report/summary/me", {}, JWT)

    assert JWT not in key
    assert jwt_fingerprint(JWT) in key
    assert len(jwt_fingerprint(JWT)) == 16


def test_cache_key_ignores_param_order():
    first = make_cache_key("/v1/act/activity-schedules", {"a": "1", "b": "2"}, JWT)
    second = make_cache_key("/v1/act/activity-schedules", {"b": "2", "a": "1"}, JWT)

    assert first == second


def test_cache_key_differs_by_jwt_params_and_path():
    base = make_cache_key("/v1/x", {"a": "1"}, JWT)

    assert base != make_cache_key("/v1/x", {"a": "1"}, OTHER_JWT)
    assert base != make_cache_key("/v1/x", {"a": "2"}, JWT)
    assert base != make_cache_key("/v1/y", {"a": "1"}, JWT)


async def test_memory_cache_returns_value_within_ttl(clock):
    cache = MemoryCache(timer=clock)
    await cache.set("k", {"value": 1}, ttl_s=120)

    clock.advance(119)
    assert await cache.get("k") == {"value": 1}


async def test_memory_cache_drops_value_after_ttl(clock):
    cache = MemoryCache(timer=clock)
    await cache.set("k", {"value": 1}, ttl_s=120)

    clock.advance(121)
    assert await cache.get("k") is None


async def test_memory_cache_keeps_ttl_per_key(clock):
    cache = MemoryCache(timer=clock)
    await cache.set("short", "a", ttl_s=60)
    await cache.set("long", "b", ttl_s=120)

    clock.advance(61)
    assert await cache.get("short") is None
    assert await cache.get("long") == "b"


async def test_memory_cache_miss_returns_none(cache):
    assert await cache.get("ยังไม่เคยเก็บ") is None


async def test_memory_cache_clear(cache):
    await cache.set("k", "v", ttl_s=60)
    cache.clear()

    assert await cache.get("k") is None
    assert len(cache) == 0


async def test_null_cache_never_stores():
    cache = NullCache()
    await cache.set("k", "v", ttl_s=60)

    assert await cache.get("k") is None
