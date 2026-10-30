"""Mock gateway for N16. Judge, ASR, and content safety never leave the process."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import MemoryCache
from gateway.pricing import Pricing
from gateway.router import RouteTable
from gateway.service import Gateway
from gateway.store import SqlStore

_ROUTES = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: mock-llm}
    fallbacks: []
  - id: asr
    task: asr
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: mock-asr}
    fallbacks: []
  - id: judge
    task: judge
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: mock-judge}
    fallbacks: []
  - id: content-safety
    task: content_safety
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: mock-content-safety}
    fallbacks: []
"""


@pytest.fixture(autouse=True)
def _project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")


@pytest.fixture
def gateway(tmp_path: Path) -> Gateway:
    routes = tmp_path / "routes.yaml"
    routes.write_text(_ROUTES, encoding="utf-8")
    progress = tmp_path / "progress.md"
    progress.write_text(
        "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
        encoding="utf-8",
    )
    return Gateway(
        routes=RouteTable(routes),
        store=SqlStore.sqlite(tmp_path / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        registry={"mock": MockAdapter()},
        model_overrides_fn=lambda: {},
    )
