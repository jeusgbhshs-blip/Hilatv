"""call_logs / alerts migration is idempotent on SQLite."""

from __future__ import annotations

from decimal import Decimal

from gateway.store import SqlStore


def test_migration_is_idempotent_and_sums_live_cost(tmp_path) -> None:
    store = SqlStore.sqlite(tmp_path / "a.sqlite")
    store.migrate()
    store.insert_log(
        {
            "created_at": "2026-10-29T12:00:00+08:00",
            "day": "2026-10-29",
            "task": "llm",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "params": {"seed": 1},
            "latency_ms": 12,
            "cost_cny": Decimal("0.5"),
            "status": "ok",
            "cache_hit": False,
            "qa_score": None,
            "live": True,
            "output": {"text": "ok"},
        }
    )
    store.insert_log(
        {
            "created_at": "2026-10-30T00:10:00+08:00",
            "day": "2026-10-30",
            "task": "llm",
            "provider": "mock",
            "model": "mock-llm",
            "params": {},
            "latency_ms": 1,
            "cost_cny": "0",
            "status": "ok",
            "cache_hit": False,
            "qa_score": None,
            "live": False,
        }
    )
    assert store.sum_cost() == Decimal("0.500000")
    assert store.sum_cost(day="2026-10-29") == Decimal("0.500000")
    assert store.sum_cost(day="2026-10-30") == Decimal("0.000000")
    row = store.list_logs()[0]
    assert row["cost"] == row["cost_cny"]
    assert row["qa_score"] is None
    assert row["params"]["seed"] == 1
