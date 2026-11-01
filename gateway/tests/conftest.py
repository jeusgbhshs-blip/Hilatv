"""Shared gateway fixtures."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import MemoryCache
from gateway.clock import SystemClock
from gateway.pricing import Pricing
from gateway.router import RouteTable
from gateway.service import Gateway
from gateway.store import SqlStore

PROGRESS_STUB = "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n"


def write_routes(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "routes.yaml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def mock_llm_routes(model: str = "mock-llm") -> str:
    return f"""
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: {model}}}
    fallbacks: []
  - id: image
    task: image
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-image}}
    fallbacks: []
  - id: video
    task: video
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-video}}
    fallbacks: []
  - id: tts
    task: tts
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-tts}}
    fallbacks: []
  - id: asr
    task: asr
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-asr}}
    fallbacks: []
  - id: music
    task: music
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-music}}
    fallbacks: []
  - id: judge
    task: judge
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-judge}}
    fallbacks: []
"""


def verified_fixture_pricing() -> Pricing:
    """Explicit synthetic rate approval for MockTransport-based vendor adapter tests."""
    pricing = Pricing.load()
    pricing.cost_bounds = {
        model: {"verified": True, "image_sizes": ["1K"], "video_resolutions": ["720p"]}
        for model in pricing.models
    }
    return pricing


class FakeProviderPricing(Pricing):
    """Trusted synthetic prices only for isolated scripted-adapter tests."""

    def upper_bound(self, model, prompt, **kwargs):
        return self.estimate(model, prompt, **kwargs)


def build_gateway(
    tmp_path: Path,
    *,
    routes: str,
    registry: dict[str, Any] | None = None,
    limits: tuple[bool, Decimal, Decimal] = (False, Decimal("0"), Decimal("0")),
    cache: Any | None = None,
    clock: Any | None = None,
    pricing: Any | None = None,
    box: dict[str, Any] | None = None,
) -> Gateway:
    path = write_routes(tmp_path, routes)
    progress = tmp_path / "progress.md"
    progress.write_text(PROGRESS_STUB, encoding="utf-8")
    store = SqlStore.sqlite(tmp_path / "gateway.sqlite")
    state = box if box is not None else {"live": limits[0], "total": limits[1], "daily": limits[2]}

    def limits_fn() -> tuple[bool, Decimal, Decimal]:
        return bool(state["live"]), Decimal(state["total"]), Decimal(state["daily"])

    adapters = {"mock": MockAdapter()}
    if registry:
        adapters.update(registry)
    return Gateway(
        routes=RouteTable(path),
        store=store,
        cache=cache or MemoryCache(),
        pricing=pricing
        if pricing is not None
        else FakeProviderPricing(
            yaml.safe_load((Path(__file__).parents[1] / "pricing.yaml").read_text())
        ),
        registry=adapters,
        limits_fn=limits_fn,
        clock=clock or SystemClock(),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )
