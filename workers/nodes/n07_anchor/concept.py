"""Concept cards from /v1/concepts. A fallback is never a pass."""

from __future__ import annotations

from typing import Any


def classify_concept(raw: object) -> tuple[str, bool, str]:
    """Return status, whether it passed, and style words.

    Status is ``absent``, ``degraded``, ``unverified``, or ``passed``.
    Only an explicit model card with ``degraded`` false and ``ok`` not false
    passes. ``template_fallback`` and ``ok`` false are degraded.
    """

    if raw is None:
        return "absent", False, ""
    if not isinstance(raw, dict):
        return "degraded", False, ""
    concept, wrapper_ok = _body(raw)
    if not isinstance(concept, dict):
        return "degraded", False, ""
    directions = concept.get("directions") if isinstance(concept.get("directions"), list) else []
    fallback = concept.get("text_source") == "template_fallback" or any(
        isinstance(item, dict) and item.get("source") == "template_fallback" for item in directions
    )
    degraded_flag = concept.get("degraded") is True or fallback
    ok_flag = concept.get("ok")
    if wrapper_ok is False or ok_flag is False or degraded_flag:
        return "degraded", False, ""
    if concept.get("text_source") == "model" and concept.get("degraded") is False:
        return "passed", True, _style(concept, directions)
    return "unverified", False, ""


def _body(raw: dict[str, Any]) -> tuple[object, object]:
    if isinstance(raw.get("payload"), dict) and "concept" in raw["payload"]:
        return raw["payload"]["concept"], raw.get("ok")
    if isinstance(raw.get("concept"), dict):
        return raw["concept"], raw.get("ok", raw["concept"].get("ok"))
    return raw, raw.get("ok")


def _style(concept: dict[str, Any], directions: list[object]) -> str:
    chosen = str(concept.get("chosen_id") or "")
    for item in directions:
        if not isinstance(item, dict):
            continue
        if chosen and str(item.get("direction_id") or "") != chosen:
            continue
        words = item.get("style_keywords")
        if isinstance(words, list):
            return " ".join(str(word) for word in words if word)
        if item.get("mood"):
            return str(item["mood"])
    return str(concept.get("title") or "")
