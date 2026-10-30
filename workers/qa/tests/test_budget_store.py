"""The regeneration ledger only grows, and it is not part of the snapshot."""

from __future__ import annotations

import json

import pytest

from workers.qa.budget_store import BudgetExhausted, ledger_path, open_project_budget
from workers.workflow.store import init_project, project_path, read_snapshot


def test_charge_is_increase_only_and_survives_a_snapshot_rollback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    init_project("p1", sentence="探针", status="completed")
    first = open_project_budget("p1")
    assert first.used == 0
    assert first.remaining == 4
    first.charge(1)
    second = open_project_budget("p1")
    second.charge(1)
    assert open_project_budget("p1").used == 2
    snapshot = project_path("p1") / "project.json"
    original = snapshot.read_text(encoding="utf-8")
    assert "used" not in json.loads(original)
    snapshot.write_text(original.replace("completed", "failed"), encoding="utf-8")
    (project_path("p1") / "nodes").mkdir(exist_ok=True)
    (project_path("p1") / "nodes" / "n08_keyframe.json").write_text("{}\n", encoding="utf-8")
    assert open_project_budget("p1").used == 2
    assert ledger_path("p1").parent.name == "_regen"
    assert not str(ledger_path("p1")).startswith(str(project_path("p1")))
    with pytest.raises(BudgetExhausted, match="已用完"):
        open_project_budget("p1").charge(3)
    assert open_project_budget("p1").used == 2
    assert read_snapshot("p1")["status"] == "failed"


def test_a_stale_handle_cannot_lower_the_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "5")
    stale = open_project_budget("p2")
    other = open_project_budget("p2")
    other.charge(2)
    stale.charge(1)
    assert open_project_budget("p2").used == 3
