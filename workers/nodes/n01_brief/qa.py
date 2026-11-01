"""Quality check for N1. A failing Brief is retried, not returned."""

from __future__ import annotations

from workers.nodes.n01_brief.platforms import aspects_match
from workers.nodes.n01_brief.schema import NodeResult
from workers.schemas.brief import Brief


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> Brief:
    if result.node != "n01_brief":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n01_brief result is not ok")
    raw = result.payload.get("brief")
    if not isinstance(raw, dict):
        raise QAError("n01_brief payload is missing brief")
    try:
        brief = Brief.model_validate(raw)
    except Exception as exc:
        raise QAError(f"brief failed validation: {exc}") from exc
    if not 5 <= brief.duration_s <= 180:
        raise QAError(f"duration_s {brief.duration_s} is outside 5–180")
    settings = brief.generation_settings
    if settings.duration_s is not None and brief.duration_s != settings.duration_s:
        raise QAError("duration_s does not match the explicit user setting")
    if settings.aspect_ratio is not None:
        if brief.aspect_ratios != [settings.aspect_ratio]:
            raise QAError("aspect_ratios do not match the explicit primary format")
    elif not aspects_match(brief.platform, brief.aspect_ratios):
        raise QAError("platform and aspect_ratios do not match")
    if len(brief.open_questions) > 2:
        raise QAError("more than 2 open questions")
    for question in brief.open_questions:
        if not question.options or question.recommended not in question.options:
            raise QAError("open question is missing its recommended option")
    return brief
