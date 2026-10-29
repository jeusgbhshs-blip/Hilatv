"""Gateway table migrations."""

from __future__ import annotations

from pathlib import Path

MIGRATION_SQL = (
    Path(__file__).resolve().parent / "migrations" / "0001_call_logs_alerts.sql"
).read_text(encoding="utf-8")

MIGRATION_VERSION = "0001"
