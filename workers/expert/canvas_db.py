"""Optional Postgres copy of the project canvas document.

The file ``canvas.json`` inside the project directory is what GET reads.
``HILATV_CANVAS_DB=1`` also upserts that document. The flag stays off when
no database is configured, so tests and CI do not open a connection.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from workers.expert.gates import GateError
from workers.identity.session import canonical_enterprise
from workers.logging import log_event


def _database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if raw.startswith("postgresql+psycopg://"):
        return "postgresql://" + raw[len("postgresql+psycopg://") :]
    return raw


def mirror_canvas(project_id: str, enterprise_id: str | None, document: dict[str, Any]) -> None:
    """Upsert ``canvas_documents`` when the flag is on. Otherwise do nothing."""

    if os.getenv("HILATV_CANVAS_DB", "").strip() != "1":
        return
    owner = canonical_enterprise(enterprise_id or "")
    if owner is None:
        return
    url = _database_url()
    if not url:
        raise GateError("画布库未配置", status=503)
    try:
        import psycopg
        from psycopg.types.json import Json
    except ImportError as exc:
        raise GateError("画布库未配置", status=503) from exc
    version = int(document.get("layout_version") or 0)
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO enterprises (enterprise_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (enterprise_id) DO NOTHING
                    """,
                    (UUID(owner), "enterprise"),
                )
                cur.execute(
                    """
                    INSERT INTO canvas_documents (
                        project_id, enterprise_id, layout_version, document
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (project_id) DO UPDATE SET
                        enterprise_id = EXCLUDED.enterprise_id,
                        layout_version = EXCLUDED.layout_version,
                        document = EXCLUDED.document,
                        updated_at = now()
                    """,
                    (project_id, UUID(owner), version, Json(document)),
                )
            conn.commit()
    except GateError:
        raise
    except Exception as exc:
        log_event(
            "canvas_db_failed",
            project_id=project_id,
            node="canvas",
            attempt=1,
            error=type(exc).__name__,
        )
        raise GateError("画布没有写入数据库") from exc
