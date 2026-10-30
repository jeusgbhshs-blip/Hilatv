"""N16 final review. The signature is reserved; T12 does not score a finished film."""

from __future__ import annotations

from typing import Any

from workers.schemas.asset import QAReport


def review_film(payload: dict[str, Any]) -> QAReport:
    """Compliance review of a finished film. Narrative VLM scoring stays in T12."""

    if not isinstance(payload.get("brief"), dict) or not isinstance(payload.get("script"), dict):
        raise ValueError("N16 final review needs a brief and a script")
    from workers.nodes.n16_review.node import run

    project_id = str(payload.get("project_id") or "n16")
    body = dict(payload)
    body.setdefault("stage", "input")
    result = run({"project_id": project_id, "payload": body})
    return QAReport.model_validate(result.payload["qa"])
