"""Alembic environment.

The URL comes from ``DATABASE_URL`` or from ``.env`` / ``.env.example``.
``postgresql://`` is rewritten to the psycopg3 SQLAlchemy driver.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _read_database_url(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return value.strip().strip('"').strip("'")
    return None


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        raw = _read_database_url(ROOT / ".env") or ""
    if not raw:
        raw = _read_database_url(ROOT / ".env.example") or ""
    if not raw:
        raise RuntimeError("DATABASE_URL is not set and .env.example has no DATABASE_URL")
    if raw.startswith("postgresql+psycopg://"):
        return raw
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://") :]
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://") :]
    raise RuntimeError("DATABASE_URL must be a postgresql URL")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
