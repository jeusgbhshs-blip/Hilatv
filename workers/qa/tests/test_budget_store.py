"""The regenerate counter is one file per project, shared by every shot."""

from __future__ import annotations

import json

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


def test_the_counter_only_increases(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "5")
    budget = open_project_budget("proj-up")
    assert budget.try_take() is True
    assert budget.try_take() is True
    stored = json.loads((tmp_path / "proj-up" / "regen_budget.json").read_text(encoding="utf-8"))
    assert stored["used"] == 2
    assert stored["increase_only"] is True
    again = open_project_budget("proj-up")
    assert again.used == 2
    assert again.try_take() is True
    assert again.used == 3


def test_try_take_n_spends_all_or_nothing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "3")
    budget = open_project_budget("proj-n")
    assert budget.try_take_n(2) is True
    assert budget.used == 2
    assert budget.try_take_n(2) is False
    assert budget.used == 2
    stored = json.loads((tmp_path / "proj-n" / "regen_budget.json").read_text(encoding="utf-8"))
    assert stored["used"] == 2


def test_try_take_n_does_not_double_charge(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    start = threading.Barrier(2)
    results: list[bool] = []

    def worker() -> None:
        start.wait()
        results.append(open_project_budget("proj-race").try_take_n(2))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
    assert open_project_budget("proj-race").used == 2


def test_project_id_cannot_escape_the_directory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    with pytest.raises(SettingsError):
        open_project_budget("../outside")
