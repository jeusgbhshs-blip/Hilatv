"""Real PostgreSQL admission/recovery gate, required in the database CI job.

Only a freshly created hp09_budget_* database is migrated or dropped. No test
touches application project files, real provider APIs, or existing charge logs.
"""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from gateway.errors import GatewayError
from gateway.store import SqlStore


@pytest.fixture
def isolated_postgres():
    if os.getenv("HILATV_REQUIRE_DB") != "1":
        pytest.skip("real PostgreSQL gate runs in required-database CI / accept-t03")
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        pytest.fail("HILATV_REQUIRE_DB=1 requires DATABASE_URL", pytrace=False)
    original = make_url(raw).set(drivername="postgresql")
    name = "hp09_budget_" + uuid.uuid4().hex
    dsn = original.set(database=name).render_as_string(hide_password=False)
    admin = psycopg.connect(
        original.render_as_string(hide_password=False), autocommit=True, connect_timeout=3
    )
    created = False
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created = True
        _gateway_migrations(original.set(database=name, drivername="postgresql+psycopg"))
        yield dsn
    finally:
        if created:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def _gateway_migrations(url):
    """Use the actual production upgrade functions, without unrelated pgvector DDL.

    The separate existing schema CI gate still upgrades/downgrades the full
    business chain. This test's isolated database exercises the gateway only.
    """
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for name in (
                    "20261029_0002_t03_gateway_logs.py",
                    "20261101_0004_hp03_budget_reservations.py",
                ):
                    spec = importlib.util.spec_from_file_location("hp09_migration", versions / name)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.upgrade()
    finally:
        engine.dispose()


def _reserve_in_process(dsn, barrier, results, total, daily):
    store = SqlStore.postgres(dsn)
    try:
        barrier.wait(timeout=15)
        decision = store.reserve_budget(
            reservation_id=str(uuid.uuid4()),
            day="2026-11-01",
            created_at="2026-11-01T23:59:59+08:00",
            estimate=Decimal("0.04"),
            total_cap=Decimal(total),
            daily_cap=Decimal(daily),
            context={"provider": "offline-fixture"},
        )
        results.put(decision["allowed"])
    finally:
        store.close()


@pytest.mark.parametrize("total,daily", [("0.05", "10"), ("10", "0.05")])
def test_postgres_multiple_processes_cannot_oversubscribe_either_cap(
    isolated_postgres, total, daily
):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    results = context.Queue()
    processes = [
        context.Process(
            target=_reserve_in_process,
            args=(isolated_postgres, barrier, results, total, daily),
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert sum(results.get(timeout=3) for _ in processes) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    store = SqlStore.postgres(isolated_postgres)
    try:
        assert store.budget_totals("2026-11-02")["reserved"] == Decimal("0.04")
    finally:
        store.close()


def test_postgres_restart_midnight_and_failed_settlement_keep_the_obligation(isolated_postgres):
    store = SqlStore.postgres(isolated_postgres)
    reservation = str(uuid.uuid4())
    admitted = store.reserve_budget(
        reservation_id=reservation,
        day="2026-11-01",
        created_at="2026-11-01T23:59:59+08:00",
        estimate=Decimal("0.04"),
        total_cap=Decimal("0.05"),
        daily_cap=Decimal("0.05"),
        context={},
    )
    assert admitted["allowed"]
    store.hold_uncertain_budget(reservation)
    store.close()
    restarted = SqlStore.postgres(isolated_postgres)
    try:
        blocked = restarted.reserve_budget(
            reservation_id=str(uuid.uuid4()),
            day="2026-11-02",
            created_at="2026-11-02T00:00:01+08:00",
            estimate=Decimal("0.04"),
            total_cap=Decimal("10"),
            daily_cap=Decimal("0.05"),
            context={},
        )
        assert not blocked["allowed"] and blocked["reason"] == "daily"
        receipt = {
            "day": "2026-11-02",
            "created_at": "2026-11-02T00:00:02+08:00",
            "task": "llm",
            "provider": "offline-fixture",
            "model": "fake",
            "latency_ms": 1,
            "cost_cny": "0.04",
            "status": "error",
            "live": True,
        }
        with pytest.raises(KeyError):
            restarted.settle_budget(reservation, {k: v for k, v in receipt.items() if k != "task"})
        assert restarted.budget_totals("2026-11-02")["reserved"] == Decimal("0.04")
        assert restarted.sum_cost() == 0
        # Fail after the charge INSERT, at the reservation UPDATE. The INSERT
        # must roll back with that update; the real held obligation must survive.
        restarted.conn.execute("""
            CREATE FUNCTION hp09_fail_settlement() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected settlement write failure'; END $$
        """)
        restarted.conn.execute("""
            CREATE TRIGGER hp09_fail_settlement BEFORE UPDATE ON budget_reservations
            FOR EACH ROW WHEN (NEW.state = 'settled')
            EXECUTE FUNCTION hp09_fail_settlement()
        """)
        restarted.conn.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="injected settlement"):
            restarted.settle_budget(reservation, receipt)
        assert restarted.sum_cost() == 0
        assert restarted.budget_totals("2026-11-02")["reserved"] == Decimal("0.04")
        restarted.conn.execute("DROP TRIGGER hp09_fail_settlement ON budget_reservations")
        restarted.conn.execute("DROP FUNCTION hp09_fail_settlement()")
        restarted.conn.commit()
        assert restarted.settle_budget(reservation, receipt) is True
        assert restarted.settle_budget(reservation, receipt) is False
        with pytest.raises(GatewayError, match="conflicting"):
            restarted.settle_budget(reservation, {**receipt, "cost_cny": "0.05"})
        assert restarted.sum_cost() == Decimal("0.04")
        assert restarted.sum_cost(day="2026-11-01") == 0
        assert restarted.sum_cost(day="2026-11-02") == Decimal("0.04")
        assert restarted.budget_totals("2026-11-02")["reserved"] == 0
    finally:
        restarted.close()
