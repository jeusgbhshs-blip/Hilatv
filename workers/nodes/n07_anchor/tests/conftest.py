"""Keep N7 files inside a temp project directory. Live calls stay off."""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.nodes.media_gateway import build_media_gateway


@pytest.fixture(autouse=True)
def _dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")


@pytest.fixture
def gateway(tmp_path: Path):
    root = tmp_path / "gateway"
    root.mkdir()
    return build_media_gateway(root)
