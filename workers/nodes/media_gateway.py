"""In-memory gateway for N8/N10 tests. No vendor keys and no MinIO."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import MemoryCache
from gateway.pricing import Pricing
from gateway.router import RouteTable, default_routes_path
from gateway.service import Gateway
from gateway.storage import MemoryObjectStore
from gateway.store import SqlStore


def build_media_gateway(directory: Path) -> Gateway:
    store = MemoryObjectStore()
    progress = directory / "progress.md"
    progress.write_text(
        "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
        encoding="utf-8",
    )
    gateway = Gateway(
        routes=RouteTable(default_routes_path()),
        store=SqlStore.sqlite(directory / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry={"mock": MockAdapter(store=store)},
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )
    gateway.media_store = store  # type: ignore[attr-defined]
    return gateway
