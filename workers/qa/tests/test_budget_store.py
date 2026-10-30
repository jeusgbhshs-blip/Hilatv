"""The regenerate counter is one file per project, shared by every shot."""

from __future__ import annotations

import pytest

from workers.qa.budget_store import open_project_budget
from workers.qa.settings import SettingsError


def test_two_shots_share_one_counter(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    first = open_project_budget("proj-a")
    assert first.try_take() is True
    second = open_project_budget("proj-a")
    assert second.allow() is True
    assert second.try_take() is True
    third = open_project_budget("proj-a")
    assert third.allow() is False
    assert third.try_take() is False
    other = open_project_budget("proj-b")
    assert other.allow() is True
    assert other.used == 0


def test_project_id_cannot_escape_the_directory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    with pytest.raises(SettingsError):
        open_project_budget("../outside")
