"""call_logs and alerts.

Postgres tables come from Alembic revision ``t03_gateway_0002``. SQLite is only
for unit tests and creates the same columns in-process.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from gateway.errors import GatewayError
from gateway.money import money, money_upper

# Kept in sync with migrations/versions/20261029_0002_t03_gateway_logs.py.
SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    seq BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    project_id TEXT,
    node TEXT,
    shot_id TEXT,
    attempt INTEGER,
    task TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    params TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_cny TEXT NOT NULL,
    status TEXT NOT NULL,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    qa_score TEXT,
    live INTEGER NOT NULL DEFAULT 0,
    fallback_reason TEXT,
    output TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_call_logs_day ON call_logs (day);
CREATE INDEX IF NOT EXISTS ix_call_logs_seq ON call_logs (seq);
CREATE TABLE IF NOT EXISTS budget_reservations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    amount_cny TEXT NOT NULL,
    state TEXT NOT NULL,
    context TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_budget_reservations_state ON budget_reservations (state);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    spent_cny TEXT NOT NULL,
    limit_cny TEXT NOT NULL,
    daily_spent_cny TEXT,
    daily_limit_cny TEXT,
    details TEXT
);
"""


class SqlStore:
    def __init__(self, conn: Any, dialect: str) -> None:
        self.conn = conn
        self.dialect = dialect
        self._lock = threading.RLock()
        self.migrate()

    @classmethod
    def sqlite(cls, path: str | Path) -> SqlStore:
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        return cls(conn, "sqlite")

    @classmethod
    def postgres(cls, url: str) -> SqlStore:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=3)
        return cls(conn, "postgres")

    def migrate(self) -> None:
        if self.dialect == "sqlite":
            with self._lock:
                self._script(SQLITE_DDL)
                self.conn.commit()
            return
        self._require_postgres_tables()

    def _require_postgres_tables(self) -> None:
        with self._lock:
            cursor = self._run(
                "SELECT to_regclass('public.call_logs') AS call_logs, "
                "to_regclass('public.alerts') AS alerts, "
                "to_regclass('public.budget_reservations') AS budget_reservations"
            )
            row = self._mapping(cursor.fetchone())
            self.conn.rollback()
        if any(row.get(name) is None for name in ("call_logs", "alerts", "budget_reservations")):
            raise GatewayError(
                "Postgres is missing gateway log or budget reservation tables. "
                "Run `alembic upgrade head`."
            )

    def close(self) -> None:
        self.conn.close()

    def insert_log(self, row: dict[str, Any], *, _commit: bool = True) -> None:
        with self._lock:
            current = self._run("SELECT COALESCE(MAX(seq), 0) AS m FROM call_logs")
            seq = int(self._mapping(current.fetchone())["m"]) + 1
            self._run(
                """
                INSERT INTO call_logs (
                    id, seq, created_at, day, project_id, node, shot_id, attempt,
                    task, provider, model, params, latency_ms, cost_cny, status,
                    cache_hit, qa_score, live, fallback_reason, output, error
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    row.get("id") or str(uuid.uuid4()),
                    seq,
                    row["created_at"],
                    row["day"],
                    row.get("project_id"),
                    row.get("node"),
                    row.get("shot_id"),
                    row.get("attempt"),
                    row["task"],
                    row["provider"],
                    row["model"],
                    json.dumps(row.get("params") or {}, ensure_ascii=False, default=str),
                    int(row["latency_ms"]),
                    format(money(row["cost_cny"]), "f"),
                    row["status"],
                    1 if row.get("cache_hit") else 0,
                    None if row.get("qa_score") is None else str(row["qa_score"]),
                    1 if row.get("live") else 0,
                    row.get("fallback_reason"),
                    _dump(row.get("output")),
                    row.get("error"),
                ),
            )
            if _commit:
                self.conn.commit()

    def insert_alert(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._run(
                """
                INSERT INTO alerts (
                    id, created_at, kind, message, spent_cny, limit_cny,
                    daily_spent_cny, daily_limit_cny, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row.get("id") or str(uuid.uuid4()),
                    row["created_at"],
                    row["kind"],
                    row["message"],
                    format(money(row["spent_cny"]), "f"),
                    format(money(row["limit_cny"]), "f"),
                    format(money(row["daily_spent_cny"]), "f"),
                    format(money(row["daily_limit_cny"]), "f"),
                    _dump(row.get("details")),
                ),
            )
            self.conn.commit()

    def sum_cost(self, *, day: str | None = None) -> Any:
        sql = "SELECT cost_cny FROM call_logs WHERE live = 1 AND cache_hit = 0"
        params: list[Any] = []
        if day is not None:
            sql += " AND day = %s"
            params.append(day)
        total = money(0)
        for row in self.fetchall(sql, params):
            total += money(row["cost_cny"])
        return money(total)

    @contextmanager
    def _budget_transaction(self) -> Iterator[None]:
        """Short database lock, shared by every gateway process, never across HTTP."""
        with self._lock:
            try:
                if self.dialect == "sqlite":
                    self._run("BEGIN IMMEDIATE")
                else:
                    # The session can already have a read transaction from list_logs.
                    self.conn.commit()
                    self._run("SELECT pg_advisory_xact_lock(%s)", (734905031,))
                yield
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def budget_totals(self, day: str) -> dict[str, Decimal]:
        with self._lock:
            pending = self.fetchall(
                "SELECT amount_cny FROM budget_reservations "
                "WHERE state IN ('reserved', 'uncertain')"
            )
            held = money(sum((money(row["amount_cny"]) for row in pending), Decimal(0)))
            return {
                "spent": self.sum_cost(),
                "daily_spent": self.sum_cost(day=day),
                "reserved": held,
                # An unfinished call can finish today, even if admitted yesterday.
                "daily_reserved": held,
            }

    def reserve_budget(
        self,
        *,
        reservation_id: str,
        day: str,
        created_at: str,
        estimate: Decimal,
        total_cap: Decimal,
        daily_cap: Decimal,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if any(not value.is_finite() or value < 0 for value in (estimate, total_cap, daily_cap)):
            raise ValueError("invalid budget amount")
        estimate, total_cap, daily_cap = money_upper(estimate), money(total_cap), money(daily_cap)
        with self._budget_transaction():
            totals = self.budget_totals(day)
            durable = self.dialect == "postgres" or any(
                item["file"]
                for item in self.fetchall("PRAGMA database_list")
                if item["name"] == "main"
            )
            reason = "ok" if durable else "nonpersistent_store"
            if (
                total_cap <= 0
                or totals["spent"] + totals["reserved"] >= total_cap
                or (totals["spent"] + totals["reserved"] + estimate > total_cap)
            ):
                reason = "total"
            elif (
                daily_cap <= 0
                or totals["daily_spent"] + totals["daily_reserved"] >= daily_cap
                or (totals["daily_spent"] + totals["daily_reserved"] + estimate > daily_cap)
            ):
                reason = "daily"
            if reason == "ok":
                for invalid in self.fetchall(
                    "SELECT context FROM budget_reservations WHERE state = 'settled_overrun'"
                ):
                    old = _load(invalid["context"])
                    if context.get("cost_bound_key") and (
                        old.get("cost_bound_key") == context["cost_bound_key"]
                    ):
                        reason = "untrusted_bound"
                        break
            if reason == "ok":
                self._run(
                    "INSERT INTO budget_reservations "
                    "(id, created_at, day, amount_cny, state, context) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        reservation_id,
                        created_at,
                        day,
                        format(estimate, "f"),
                        "reserved",
                        _dump(context),
                    ),
                )
            return {**totals, "reason": reason, "allowed": reason == "ok"}

    def settle_budget(self, reservation_id: str, row: dict[str, Any]) -> bool:
        """Persist the bill and remove its hold in the same transaction, once."""
        with self._budget_transaction():
            found = self.fetchall(
                "SELECT state, amount_cny FROM budget_reservations WHERE id = %s", (reservation_id,)
            )
            if not found:
                raise GatewayError("unknown budget reservation")
            if found[0]["state"] in {"settled", "settled_overrun"}:
                old = self.fetchall(
                    "SELECT cost_cny FROM call_logs WHERE id = %s", (reservation_id,)
                )
                if not old or money(old[0]["cost_cny"]) != money(row["cost_cny"]):
                    raise GatewayError("conflicting budget settlement")
                return False
            if found[0]["state"] not in {"reserved", "uncertain"}:
                raise GatewayError("budget reservation is not chargeable")
            cost = money(row["cost_cny"])
            if not cost.is_finite() or cost < 0:
                raise GatewayError("invalid provider cost")
            state = "settled_overrun" if cost > money(found[0]["amount_cny"]) else "settled"
            self.insert_log({**row, "id": reservation_id}, _commit=False)
            self._run(
                "UPDATE budget_reservations SET state = %s WHERE id = %s", (state, reservation_id)
            )
            return True

    def hold_uncertain_budget(self, reservation_id: str) -> None:
        """A timeout is not evidence the vendor billed zero. Hold until reconciled."""
        with self._budget_transaction():
            self._run(
                "UPDATE budget_reservations SET state = 'uncertain' "
                "WHERE id = %s AND state = 'reserved'",
                (reservation_id,),
            )

    def list_reservations(self) -> list[dict[str, Any]]:
        return self.fetchall("SELECT * FROM budget_reservations ORDER BY created_at, id")

    def list_logs(self, *, project_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM call_logs"
        params: list[Any] = []
        if project_id is not None:
            sql += " WHERE project_id = %s"
            params.append(project_id)
        sql += " ORDER BY seq ASC"
        rows = self.fetchall(sql, params)
        for row in rows:
            row["params"] = _load(row.get("params"))
            row["output"] = _load(row.get("output")) if row.get("output") else None
            row["cost"] = row["cost_cny"]
            row["cache_hit"] = int(row["cache_hit"] or 0)
            row["live"] = int(row["live"] or 0)
        return rows

    def list_alerts(self) -> list[dict[str, Any]]:
        rows = self.fetchall("SELECT * FROM alerts ORDER BY created_at ASC, id ASC")
        for row in rows:
            row["details"] = _load(row.get("details")) if row.get("details") else None
        return rows

    def fetchall(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._run(sql, params)
            return [self._mapping(row) for row in cursor.fetchall()]

    def _run(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        statement = sql if self.dialect == "postgres" else sql.replace("%s", "?")
        return self.conn.execute(statement, tuple(params))

    def _script(self, sql: str) -> None:
        for statement in _statements(sql):
            self.conn.execute(statement)

    @staticmethod
    def _mapping(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return dict(row)
        return dict(row)


def open_store_from_env() -> SqlStore:
    mode = os.getenv("HILATV_GATEWAY_STORE", "auto").strip().lower() or "auto"
    url = os.getenv("DATABASE_URL", "").strip()
    sqlite_path = os.getenv("HILATV_SQLITE_PATH", "").strip()
    if mode == "sqlite":
        return SqlStore.sqlite(sqlite_path or ":memory:")
    if mode == "postgres":
        if not url:
            raise GatewayError("HILATV_GATEWAY_STORE=postgres requires DATABASE_URL")
        return SqlStore.postgres(url)
    if url and postgres_reachable(url):
        return SqlStore.postgres(url)
    if sqlite_path:
        return SqlStore.sqlite(sqlite_path)
    return SqlStore.sqlite(":memory:")


def postgres_reachable(url: str) -> bool:
    if not url:
        return False
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return False
    return True


def _statements(sql: str) -> list[str]:
    return [part.strip() for part in sql.split(";") if part.strip()]


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)
