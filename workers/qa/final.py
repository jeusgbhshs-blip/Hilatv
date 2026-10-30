"""Compliance QAReport for a finished film.

Full-film scoring (frames, transcript, hard flaws, brand, director decisions)
lives in ``workers.nodes.n16_final_review``. This function stays the T12 hook
and only returns the T20 compliance report.
"""

from __future__ import annotations

from typing import Any

from workers.schemas.asset import QAReport


def review_film(payload: dict[str, Any]) -> QAReport:
    """Compliance review of a finished film. Narrative scoring is n16_final_review."""

    if not isinstance(payload.get("brief"), dict) or not isinstance(payload.get("script"), dict):
        raise ValueError("N16 final review needs a brief and a script")
    from workers.nodes.n16_review.node import run

    project_id = str(payload.get("project_id") or "n16")
    body = dict(payload)
    body.setdefault("stage", "input")
    result = run({"project_id": project_id, "payload": body})
    return QAReport.model_validate(result.payload["qa"])
