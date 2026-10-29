"""Response cache. Redis when it is reachable, otherwise an in-process map."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Protocol

from gateway.logging import log_event


class Cache(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any], ttl: int) -> None: ...


def make_cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, raw = item
            if expires < time.monotonic():
                del self._data[key]
                return None
            loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            return None
        return loaded

    def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        raw = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, raw)


class RedisCache:
    def __init__(
        self, url: str | None = None, client: Any = None, prefix: str = "hilatv:gw:"
    ) -> None:
        if client is None:
            import redis

            client = redis.Redis.from_url(url or "", socket_connect_timeout=1, socket_timeout=1)
        self._client = client
        self._prefix = prefix

    def ping(self) -> None:
        self._client.ping()

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(self._prefix + key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            return None
        return loaded

    def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        self._client.set(
            self._prefix + key,
            json.dumps(value, ensure_ascii=False, default=str),
            ex=int(ttl),
        )


def open_cache(url: str | None) -> Cache:
    if not url:
        return MemoryCache()
    try:
        cache = RedisCache(url=url)
        cache.ping()
    except Exception:
        log_event("cache_redis_unavailable")
        return MemoryCache()
    return cache


def redis_reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        RedisCache(url=url).ping()
    except Exception:
        return False
    return True
