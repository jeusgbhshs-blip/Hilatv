"""Keep node tests off the developer's live gateway."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
