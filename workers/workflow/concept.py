"""N3 until T15: one automatic direction, the 「你帮我选」 path.

No model call. Three concept cards are T15.
"""

from __future__ import annotations

from typing import Any


class ConceptError(ValueError):
    """The automatic direction is not usable."""


def choose_direction(brief: dict[str, Any]) -> dict[str, Any]:
    direction = str(brief.get("video_type") or "").strip() or "产品展示型"
    ratios = brief.get("aspect_ratios") or []
    aspect = str(ratios[0]) if ratios else "9:16"
    concept = {
        "selection": "你帮我选",
        "auto": True,
        "direction": direction,
        "title": str(brief.get("goal") or direction),
        "duration_s": brief.get("duration_s"),
        "aspect_ratio": aspect,
        "note": "T15 之前不生成三张方案卡，系统自动选定单一方向",
    }
    check_concept(concept)
    return concept


def check_concept(concept: dict[str, Any]) -> None:
    if concept.get("selection") != "你帮我选" or concept.get("auto") is not True:
        raise ConceptError("concept must be the automatic 你帮我选 choice")
    if not str(concept.get("direction") or "").strip():
        raise ConceptError("concept is missing a direction")
