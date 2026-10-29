"""Same input, including seed, hits the cache and skips the adapter."""

from __future__ import annotations

import fakeredis
from pydantic import BaseModel

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import RedisCache
from gateway.tests.conftest import build_gateway, mock_llm_routes


class Brief(BaseModel):
    goal: str


class CountingMock(MockAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def invoke(self, call):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().invoke(call)


def test_seed_is_part_of_the_cache_key(tmp_path) -> None:
    counter = CountingMock()
    gateway = build_gateway(
        tmp_path,
        routes=mock_llm_routes(),
        registry={"mock": counter},
    )
    first = gateway.generate_text("hello", schema=Brief, seed=1)
    second = gateway.generate_text("hello", schema=Brief, seed=1)
    third = gateway.generate_text("hello", schema=Brief, seed=2)
    assert first == second
    assert counter.calls == 2
    assert Brief.model_validate(third)
    logs = gateway.store.list_logs()
    assert [row["status"] for row in logs] == ["ok", "cache_hit", "ok"]
    assert logs[1]["cache_hit"] == 1
    assert logs[1]["cost_cny"] == "0.000000"
    assert counter.calls == 2


def test_redis_cache_skips_the_adapter(tmp_path) -> None:
    counter = CountingMock()
    cache = RedisCache(client=fakeredis.FakeRedis())
    gateway = build_gateway(
        tmp_path,
        routes=mock_llm_routes(),
        registry={"mock": counter},
        cache=cache,
    )
    gateway.generate_text("redis", seed=4)
    gateway.generate_text("redis", seed=4)
    assert counter.calls == 1
    assert gateway.store.list_logs()[1]["status"] == "cache_hit"


def test_redis_cache_roundtrip() -> None:
    cache = RedisCache(client=fakeredis.FakeRedis())
    cache.set("k", {"output": {"text": "a"}, "provider": "mock", "model": "m"}, ttl=30)
    assert cache.get("k") == {"output": {"text": "a"}, "provider": "mock", "model": "m"}
    assert cache.get("missing") is None
