"""Concept cards from N3 / POST /v1/concepts. A 200 can still be a fallback.

``ok`` false, ``degraded`` true, or ``template_fallback`` cards are not a pass.
Missing markers are the pre-card stub, not a fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConceptView:
    degraded: bool
    ok: bool | None
    text_source: str

    def as_public(self) -> dict[str, Any]:
        return {
            "concept_degraded": self.degraded,
            "concept_ok": self.ok,
            "concept_text_source": self.text_source,
        }


def classify_concept(payload: Any) -> ConceptView:
    """Read a stored concept, a node patch, or a ``/v1/concepts`` body."""

    if not isinstance(payload, dict):
        return ConceptView(False, None, "")
    concept = payload.get("concept") if isinstance(payload.get("concept"), dict) else payload
    if not isinstance(concept, dict):
        return ConceptView(False, None, "")
    text_source = str(concept.get("text_source") or "")
    directions = concept.get("directions")
    fallback_card = False
    if isinstance(directions, list):
        fallback_card = any(
            isinstance(item, dict) and item.get("source") == "template_fallback"
            for item in directions
        )
    ok_values = [payload.get("ok"), concept.get("ok")]
    ok_false = any(value is False for value in ok_values)
    ok_true = any(value is True for value in ok_values)
    degraded = bool(
        concept.get("degraded") is True
        or text_source == "template_fallback"
        or fallback_card
        or ok_false
    )
    if degraded:
        source = text_source or ("template_fallback" if fallback_card else "")
        return ConceptView(True, False, source)
    if ok_true and text_source == "model" and not fallback_card:
        return ConceptView(False, True, "model")
    return ConceptView(False, None, text_source)


def delivery_passes(shot_reviews: list[dict[str, Any]], concept: Any) -> bool:
    """Pass only when every shot was visually reviewed and the concept is not a fallback."""

    view = classify_concept(concept)
    if view.degraded or view.ok is False:
        return False
    if not shot_reviews:
        return False
    for item in shot_reviews:
        if item.get("visual_reviewed") is not True:
            return False
        if item.get("quality_pass") is not True:
            return False
    return True


def read_project_concept(directory: Path) -> Any:
    path = directory / "nodes" / "n03_concept.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
