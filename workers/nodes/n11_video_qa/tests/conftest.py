"""Keep N11 fixture files inside the project directory."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _media_stays_in_the_project(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
