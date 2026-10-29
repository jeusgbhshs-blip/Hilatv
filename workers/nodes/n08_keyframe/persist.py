"""Write Candidate documents when an enterprise id and Postgres are both present.

The candidates table needs ``enterprise_id``. N8 still returns the documents when
the database is absent, so CI does not need Postgres.
"""

from __future__ import annotations

import os

from workers.logging import log_event
from workers.schemas.asset import Candidate


def persist_candidates(
    candidates: list[Candidate],
    *,
    enterprise_id: str | None,
    project_id: str,
    node: str,
) -> int:
    if not enterprise_id or not candidates:
        return 0
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        log_event(
            "candidate_persist_skipped",
            project_id=project_id,
            node=node,
            reason="no database",
        )
        return 0
    from gateway.store import postgres_reachable

    if not postgres_reachable(url):
        log_event(
            "candidate_persist_skipped",
            project_id=project_id,
            node=node,
            reason="database unreachable",
        )
        return 0
    try:
        return _insert(url, enterprise_id, candidates)
    except Exception as exc:
        log_event(
            "candidate_persist_skipped",
            project_id=project_id,
            node=node,
            reason=str(exc)[:300],
        )
        return 0


def _insert(url: str, enterprise_id: str, candidates: list[Candidate]) -> int:
    import psycopg
    from psycopg.types.json import Jsonb

    written = 0
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for candidate in candidates:
                document = candidate.model_dump(mode="json")
                cur.execute(
                    """
                    INSERT INTO candidates (candidate_id, enterprise_id, shot_id, document)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (candidate_id) DO UPDATE
                    SET shot_id = EXCLUDED.shot_id,
                        document = EXCLUDED.document,
                        updated_at = now()
                    """,
                    (candidate.candidate_id, enterprise_id, candidate.shot_id, Jsonb(document)),
                )
                written += 1
        conn.commit()
    return written
