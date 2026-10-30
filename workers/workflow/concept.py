"""How a finished N3 card set becomes the selected direction.

Card generation lives in ``workers.nodes.n03_concept``. This module only
applies 「你帮我选」 or a direction id the user already picked.
"""

from __future__ import annotations

from typing import Any


class ConceptError(ValueError):
    """The selected direction is not one of the three cards."""

    retryable = False


def apply_selection(
    directions: list[dict[str, Any]],
    selection: str | None,
    brief: dict[str, Any],
) -> dict[str, Any]:
    if not directions:
        raise ConceptError("concept has no directions")
    ids = [str(item.get("direction_id") or "") for item in directions]
    if selection and selection != "你帮我选" and selection not in ids:
        raise ConceptError(f"unknown direction {selection}")
    auto = not selection or selection == "你帮我选"
    chosen_id = ids[0] if auto else selection
    chosen = next(item for item in directions if str(item.get("direction_id")) == chosen_id)
    ratios = brief.get("aspect_ratios") or []
    aspect = str(ratios[0]) if ratios else "9:16"
    return {
        "selection": "你帮我选" if auto else chosen_id,
        "auto": auto,
        "direction": str(brief.get("video_type") or chosen_id),
        "title": chosen.get("title") or chosen_id,
        "duration_s": brief.get("duration_s"),
        "aspect_ratio": aspect,
        "chosen_id": chosen_id,
        "directions": directions,
    }


def choose_direction(brief: dict[str, Any]) -> dict[str, Any]:
    """Automatic 「你帮我选」 when the caller has not built cards yet.

    The film activity runs N3, which returns the same selection label plus
    three directions. This helper stays for a caller that only has a Brief.
    """

    direction = str(brief.get("video_type") or "").strip() or "产品展示型"
    ratios = brief.get("aspect_ratios") or []
    aspect = str(ratios[0]) if ratios else "9:16"
    return {
        "selection": "你帮我选",
        "auto": True,
        "direction": direction,
        "title": str(brief.get("goal") or direction),
        "duration_s": brief.get("duration_s"),
        "aspect_ratio": aspect,
        "note": "未生成方案卡时自动选定",
    }
