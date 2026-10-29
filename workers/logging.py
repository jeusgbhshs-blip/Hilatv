"""Structured JSON logs. Fields follow AGENTS.md: project_id, node, shot_id, attempt."""

from __future__ import annotations

import json
import sys


def log_event(
    event: str,
    *,
    project_id: str | None = None,
    node: str | None = None,
    shot_id: str | None = None,
    attempt: int | None = None,
    **fields: object,
) -> None:
    record: dict[str, object] = {
        "event": event,
        "project_id": project_id,
        "node": node,
        "shot_id": shot_id,
        "attempt": attempt,
    }
    record.update(fields)
    compact = {key: value for key, value in record.items() if value is not None}
    sys.stdout.write(json.dumps(compact, ensure_ascii=False) + "\n")
    sys.stdout.flush()
