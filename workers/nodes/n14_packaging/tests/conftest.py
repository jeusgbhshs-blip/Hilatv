from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _offline_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
