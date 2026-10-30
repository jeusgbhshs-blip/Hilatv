"""SEC-63: late-finish audit, crash reconciliation, unsaved generations, bounded ledger."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from workers.qa.budget_store import open_project_budget
from workers.qa.settings import SettingsError

NODE = "n16_final_review"


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("HILATV_BUDGET_RESERVE_TTL_S", raising=False)
    monkeypatch.delenv("HILATV_BUDGET_AUDIT_MAX", raising=False)
    monkeypatch.delenv("HILATV_BUDGET_EXPIRED_TOKENS_MAX", raising=False)
    monkeypatch.delenv("HILATV_BUDGET_EXPIRED_RETENTION_S", raising=False)


def _ledger(tmp_path: Path, project_id: str) -> dict:
    return json.loads((tmp_path / project_id / "regen_budget.json").read_text(encoding="utf-8"))


def _expire(tmp_path: Path, project_id: str, key: str) -> None:
    path = tmp_path / project_id / "regen_budget.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["reserved"][key]["expires"] = 0
    path.write_text(json.dumps(stored) + "\n", encoding="utf-8")


def _events(out: str, name: str) -> list[dict]:
    found = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        record = json.loads(line)
        if record.get("event") == name:
            found.append(record)
    return found


# --- item 1 -----------------------------------------------------------------


def test_late_top_up_over_the_cap_is_audited_and_holds_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from workers.workflow.store import init_project, read_snapshot

    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    master = tmp_path / "p-over" / "master.mp4"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"master")
    init_project("p-over", sentence="一句", status="completed", deliverable=str(master))
    budget = open_project_budget("p-over", node=NODE)
    status, token = budget.begin_batch(2, "stuck")
    assert status == "begun"
    _expire(tmp_path, "p-over", "stuck")
    # The expired hold is released, so another caller spends the whole cap.
    assert open_project_budget("p-over").try_take_n(2) is True
    assert open_project_budget("p-over").used == 2
    capsys.readouterr()
    before = time.time()
    assert budget.finish_batch(2, "stuck", token) == "audited"
    after = time.time()
    # Real generations are recorded even though they push used past the cap.
    assert budget.used == 4
    assert budget.used > budget.limit
    entry = _ledger(tmp_path, "p-over")["audit"][token]
    assert entry["count"] == 2
    assert entry["reason"] == "late"
    assert entry["project_id"] == "p-over"
    assert entry["node"] == NODE
    assert before <= entry["at"] <= after
    assert entry["used_before"] == 2
    assert entry["used_after"] == 4
    assert entry["cap"] == 2
    assert entry["over_cap"] is True
    (event,) = _events(capsys.readouterr().out, "regen_budget_late_charge")
    assert event["project_id"] == "p-over"
    assert event["node"] == NODE
    assert event["over_cap"] is True
    assert event["charged"] == 2
    assert event["used_after"] == 4
    snapshot = read_snapshot("p-over") or {}
    assert snapshot["status"] == "needs_human_review"
    assert snapshot["paused"] is True
    assert not snapshot.get("deliverable")
    # Nothing else fits, and a replay does not bill again.
    assert open_project_budget("p-over").try_take() is False
    assert budget.finish_batch(2, "stuck", token) == "already"
    assert open_project_budget("p-over").used == 4


def test_on_time_finish_entry_carries_the_same_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-ok", node=NODE)
    _status, token = budget.begin_batch(1, "k")
    assert budget.finish_batch(1, "k", token) == "taken"
    entry = _ledger(tmp_path, "p-ok")["audit"][token]
    assert entry["reason"] == "finished"
    assert entry["project_id"] == "p-ok"
    assert entry["node"] == NODE
    assert entry["over_cap"] is False
    assert isinstance(entry["at"], float)


# --- items 2 and 3 ----------------------------------------------------------


def test_generated_but_unsaved_shot_is_billed_at_finish(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-unsaved", node=NODE)
    _status, token = budget.begin_batch(2, "k")
    assert budget.note_generated("k", token, "S01") == "noted"
    assert budget.note_generated("k", token, "S02") == "noted"
    assert budget.used == 0
    assert budget.reserved == 2
    # Only S01 was saved, but both were generated.
    assert budget.finish_batch(1, "k", token) == "taken"
    assert budget.used == 2
    assert budget.reserved == 0


def test_noted_shots_never_exceed_the_reservation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-many", node=NODE)
    _status, token = budget.begin_batch(1, "k")
    budget.note_generated("k", token, "S01")
    budget.note_generated("k", token, "S01")
    budget.note_generated("k", token, "S02")
    assert _ledger(tmp_path, "p-many")["reserved"]["k"]["generated"] == ["S01"]
    assert budget.finish_batch(3, "k", token) == "taken"
    assert budget.used == 1


def test_expiry_bills_shots_of_a_worker_that_crashed_after_saving(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from workers.workflow.store import init_project, read_snapshot

    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    init_project("p-crash", sentence="一句", status="completed")
    budget = open_project_budget("p-crash", node=NODE)
    _status, token = budget.begin_batch(2, "k")
    budget.note_generated("k", token, "S01")
    # The worker saved S01 and then died. finish_batch is never called.
    _expire(tmp_path, "p-crash", "k")
    capsys.readouterr()
    assert open_project_budget("p-crash").batch_status("k") == "free"
    assert open_project_budget("p-crash").used == 1
    ledger = _ledger(tmp_path, "p-crash")
    entry = ledger["audit"][token]
    assert entry["reason"] == "reconciled"
    assert entry["count"] == 1
    assert entry["node"] == NODE
    assert entry["project_id"] == "p-crash"
    assert ledger["expired_tokens"][token]["billed"] == 1
    (event,) = _events(capsys.readouterr().out, "regen_budget_late_charge")
    assert event["reason"] == "reconciled"
    assert (read_snapshot("p-crash") or {})["status"] == "needs_human_review"
    # Reading again does not bill again.
    assert open_project_budget("p-crash").used == 1


def test_late_finish_after_reconcile_tops_up_only_the_difference(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-top", node=NODE)
    _status, token = budget.begin_batch(3, "k")
    budget.note_generated("k", token, "S01")
    _expire(tmp_path, "p-top", "k")
    assert open_project_budget("p-top").used == 1
    # The slow worker comes back and reports two saved shots.
    assert budget.finish_batch(2, "k", token) == "audited"
    assert budget.used == 2
    assert _ledger(tmp_path, "p-top")["audit"][token]["count"] == 2
    assert token not in _ledger(tmp_path, "p-top").get("expired_tokens", {})
    assert budget.finish_batch(3, "k", token) == "already"
    assert budget.used == 2


def test_finish_matching_the_reconciled_count_is_already(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-same", node=NODE)
    _status, token = budget.begin_batch(2, "k")
    budget.note_generated("k", token, "S01")
    budget.note_generated("k", token, "S02")
    _expire(tmp_path, "p-same", "k")
    assert open_project_budget("p-same").used == 2
    assert budget.finish_batch(2, "k", token) == "already"
    assert budget.used == 2


def test_note_on_an_expired_token_bills_immediately_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-note", node=NODE)
    _status, token = budget.begin_batch(2, "k")
    _expire(tmp_path, "p-note", "k")
    assert open_project_budget("p-note").used == 0
    assert budget.note_generated("k", token, "S01") == "audited"
    assert budget.used == 1
    assert budget.note_generated("k", token, "S01") == "already"
    assert budget.used == 1
    assert budget.finish_batch(0 + 1, "k", token) == "already"
    assert budget.used == 1


def test_unknown_token_cannot_raise_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    budget = open_project_budget("p-forge", node=NODE)
    budget.begin_batch(2, "k")
    assert budget.note_generated("k", "f" * 32, "S01") == "refused"
    assert budget.finish_batch(2, "k", "f" * 32) == "refused"
    assert budget.used == 0


# --- item 4 -----------------------------------------------------------------


def test_audit_is_compacted_without_touching_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "50")
    monkeypatch.setenv("HILATV_BUDGET_AUDIT_MAX", "3")
    budget = open_project_budget("p-audit", node=NODE)
    tokens = []
    for index in range(7):
        _status, token = budget.begin_batch(2, f"k{index}")
        assert budget.finish_batch(2, f"k{index}", token) == "taken"
        tokens.append(token)
    ledger = _ledger(tmp_path, "p-audit")
    assert ledger["used"] == 14
    assert len(ledger["audit"]) == 3
    assert set(ledger["audit"]) == set(tokens[-3:])
    folded = ledger["audit_compacted"]
    assert folded["entries"] == 4
    assert folded["count"] == 8
    # Totals still add up to used.
    assert folded["count"] + sum(row["count"] for row in ledger["audit"].values()) == 14
    # A compacted token cannot be billed again.
    assert budget.finish_batch(2, "k0", tokens[0]) == "refused"
    assert budget.used == 14


def test_expired_tokens_are_bounded_by_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "50")
    monkeypatch.setenv("HILATV_BUDGET_EXPIRED_TOKENS_MAX", "2")
    budget = open_project_budget("p-exp", node=NODE)
    tokens = []
    for index in range(5):
        _status, token = budget.begin_batch(1, f"k{index}")
        tokens.append(token)
        _expire(tmp_path, "p-exp", f"k{index}")
        budget.batch_status(f"k{index}")
        time.sleep(0.01)
    remembered = _ledger(tmp_path, "p-exp")["expired_tokens"]
    assert len(remembered) == 2
    assert set(remembered) == set(tokens[-2:])
    assert budget.used == 0


def test_expired_tokens_age_out_after_retention(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "50")
    budget = open_project_budget("p-age", node=NODE)
    _status, token = budget.begin_batch(1, "k")
    _expire(tmp_path, "p-age", "k")
    budget.batch_status("k")
    path = tmp_path / "p-age" / "regen_budget.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert token in stored["expired_tokens"]
    stored["expired_tokens"][token]["expired_at"] = 0
    path.write_text(json.dumps(stored) + "\n", encoding="utf-8")
    capsys.readouterr()
    budget.batch_status("k")
    assert "expired_tokens" not in _ledger(tmp_path, "p-age")
    (event,) = _events(capsys.readouterr().out, "regen_budget_expired_token_dropped")
    assert event["project_id"] == "p-age"
    assert budget.used == 0


def test_retention_is_never_shorter_than_twice_the_ttl(monkeypatch) -> None:
    from workers.qa.budget_store import expired_retention_s

    monkeypatch.setenv("HILATV_BUDGET_RESERVE_TTL_S", "900")
    monkeypatch.setenv("HILATV_BUDGET_EXPIRED_RETENTION_S", "10")
    assert expired_retention_s() == 1800


def test_an_expired_token_that_can_still_top_up_is_not_folded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "50")
    monkeypatch.setenv("HILATV_BUDGET_AUDIT_MAX", "1")
    budget = open_project_budget("p-keep", node=NODE)
    _status, stale = budget.begin_batch(2, "old")
    budget.note_generated("old", stale, "S01")
    _expire(tmp_path, "p-keep", "old")
    budget.batch_status("old")
    _status, fresh = budget.begin_batch(1, "new")
    assert budget.finish_batch(1, "new", fresh) == "taken"
    ledger = _ledger(tmp_path, "p-keep")
    assert stale in ledger["audit"]
    assert budget.finish_batch(2, "old", stale) == "audited"
    assert budget.used == 3


@pytest.mark.parametrize(
    "name",
    ["HILATV_BUDGET_AUDIT_MAX", "HILATV_BUDGET_EXPIRED_TOKENS_MAX"],
)
def test_bad_bounds_are_rejected(tmp_path: Path, monkeypatch, name: str) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    monkeypatch.setenv(name, "0")
    with pytest.raises(SettingsError):
        open_project_budget("p-bad")


def test_ledger_from_before_sec63_still_reads(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "10")
    folder = tmp_path / "p-old"
    folder.mkdir()
    (folder / "regen_budget.json").write_text(
        json.dumps(
            {
                "used": 3,
                "applied": {"a": 1},
                "reserved": {"b": {"count": 1, "expires": time.time() + 900, "token": "t1"}},
                "expired_tokens": {"t0": {"count": 2, "key": "c"}},
                "audit": {"t9": {"count": 2, "key": "d", "reason": "late"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    budget = open_project_budget("p-old", node=NODE)
    assert budget.used == 3
    assert budget.reserved == 1
    assert budget.finish_batch(1, "c", "t0") == "audited"
    assert budget.used == 4
    assert budget.finish_batch(1, "b", "t1") == "taken"
    assert budget.used == 5
