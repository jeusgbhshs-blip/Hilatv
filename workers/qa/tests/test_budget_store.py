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


def test_can_take_refuses_before_spending(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    budget = open_project_budget("proj-fit")
    assert budget.try_take() is True
    assert budget.can_take(1) is True
    assert budget.can_take(2) is False
    assert budget.used == 1
    assert budget.try_take_n(2) is False
    assert budget.used == 1


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


def test_the_same_batch_key_charges_once_when_the_budget_has_room(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "10")
    start = threading.Barrier(2)
    begun: list[str] = []

    def worker() -> None:
        start.wait()
        budget = open_project_budget("proj-once")
        status = budget.begin_batch(2, "batch-a")
        begun.append(status)
        if status == "begun":
            assert budget.finish_batch(2, "batch-a") is True

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert begun.count("begun") == 1
    assert open_project_budget("proj-once").used == 2
    assert open_project_budget("proj-once").finish_batch(2, "batch-a") is False
    assert open_project_budget("proj-once").used == 2


def test_two_keys_cannot_both_reserve_the_same_slots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    start = threading.Barrier(2)
    begun: list[str] = []

    def worker(key: str) -> None:
        start.wait()
        status = open_project_budget("proj-slots").begin_batch(2, key)
        begun.append(status)
        if status == "begun":
            assert open_project_budget("proj-slots").try_take_n(1) is False
            assert open_project_budget("proj-slots").finish_batch(2, key) is True

    threads = [
        threading.Thread(target=worker, args=("batch-a",)),
        threading.Thread(target=worker, args=("batch-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert begun.count("begun") == 1
    assert "refused" in begun
    budget = open_project_budget("proj-slots")
    assert budget.used == 2
    assert budget.reserved == 0
    assert budget.try_take_n(1) is False


def test_try_take_n_sees_a_live_reservation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "3")
    budget = open_project_budget("proj-hold")
    assert budget.begin_batch(2, "batch-a") == "begun"
    assert budget.used == 0
    assert budget.can_take(2) is False
    assert budget.try_take_n(2) is False
    assert budget.try_take_n(1) is True
    assert budget.used == 1
    assert budget.finish_batch(2, "batch-a") is True
    assert budget.used == 3
    assert budget.reserved == 0
    stored = json.loads((tmp_path / "proj-hold" / "regen_budget.json").read_text(encoding="utf-8"))
    assert stored["used"] == 3
    assert "reserved" not in stored


def test_partial_finish_charges_only_the_saved_shots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("proj-part")
    assert budget.begin_batch(2, "batch-a") == "begun"
    assert budget.finish_batch(1, "batch-a") is True
    assert budget.used == 1
    assert budget.reserved == 0
    assert budget.can_take(3) is True
    assert budget.try_take_n(1) is True
    assert budget.used == 2
    assert budget.finish_batch(1, "batch-a") is False
    assert budget.used == 2


def test_expired_reservation_is_released_and_the_project_is_held(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    from workers.workflow.store import init_project, read_snapshot

    master = tmp_path / "proj-stale" / "master.mp4"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"master-bytes")
    init_project("proj-stale", sentence="一句", status="completed", deliverable=str(master))
    budget = open_project_budget("proj-stale")
    assert budget.begin_batch(2, "stuck") == "begun"
    path = tmp_path / "proj-stale" / "regen_budget.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["reserved"]["stuck"]["expires"] = 0
    path.write_text(json.dumps(stored) + "\n", encoding="utf-8")
    assert budget.batch_status("stuck") == "free"
    assert budget.used == 0
    assert budget.reserved == 0
    assert budget.can_take(2) is True
    snapshot = read_snapshot("proj-stale") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    assert snapshot["held_deliverable"] == str(master.resolve())
    assert master.read_bytes() == b"master-bytes"


def test_project_id_cannot_escape_the_directory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    with pytest.raises(SettingsError):
        open_project_budget("../outside")
