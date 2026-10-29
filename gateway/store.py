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
from pathlib import Path
from typing import Any

from gateway.errors import GatewayError
from gateway.money import money

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
        conn = sqlite3.connect(str(path), check_same_thread=False)
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
                "to_regclass('public.alerts') AS alerts"
            )
            row = self._mapping(cursor.fetchone())
            self.conn.rollback()
        if row.get("call_logs") is None or row.get("alerts") is None:
            raise GatewayError(
                "Postgres is missing call_logs or alerts. "
                "Run `alembic upgrade head` (revision t03_gateway_0002)."
            )

    def close(self) -> None:
        self.conn.close()

    def insert_log(self, row: dict[str, Any]) -> None:
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
