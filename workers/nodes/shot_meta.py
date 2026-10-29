"""How N8 and N10 read a storyboard shot.

N7 has not produced image anchors yet, and product compositing is T13.
Descriptions stay text. On-screen copy is stripped so a model is not asked to draw it.
"""

from __future__ import annotations

from typing import Any

from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import GenerationMode, Shot

# Moves that need a matching closing frame (orbit, push, pull, rise).
END_FRAME_CAMERAS = frozenset({"gentle_arc", "slow_push_in", "slow_pull_back", "rise_reveal"})


def shot_family(shot: Shot) -> str:
    """Gateway ``shot_type`` for N10. ``motion_graphics`` is not sent to a model."""

    if shot.generation_mode is GenerationMode.motion_graphics:
        return "motion_graphics"
    if "人物" in shot.purpose or any(ref.startswith("person:") for ref in shot.subject_refs):
        return "person"
    if shot.generation_mode is GenerationMode.reference_to_video and len(shot.subject_refs) >= 2:
        return "multi_ref"
    if shot.generation_mode in {
        GenerationMode.product_composite,
        GenerationMode.reference_to_video,
    }:
        return "product"
    if any(ref.startswith("product:") for ref in shot.subject_refs):
        return "product"
    return "atmosphere"


def needs_end_frame(shot: Shot) -> bool:
    if shot.generation_mode is GenerationMode.motion_graphics:
        return False
    if shot.generation_mode is GenerationMode.first_last_frame:
        return True
    return shot.camera in END_FRAME_CAMERAS


def motion_strength(shot: Shot, preset_strength: str) -> str:
    """Product shots stay low. Atmosphere shots are at least medium."""

    family = shot_family(shot)
    strength = preset_strength or "low"
    if family == "product":
        return "low"
    if family == "atmosphere" and strength == "low":
        return "medium"
    return strength


def blocked_text(shot: Shot) -> list[str]:
    return [card.text for card in shot.on_screen_text if card.text]


def scrub(text: str, blocked: list[str]) -> str:
    cleaned = text
    for item in blocked:
        if item:
            cleaned = cleaned.replace(item, " ")
    return " ".join(cleaned.split())


def describe(
    shot: Shot,
    brand: BrandKit | None,
    brief: Brief | None,
    scene_anchors: list[Any] | None = None,
    style_anchor: Any | None = None,
) -> tuple[str, str, str]:
    """Subject, scene, and style lines with on-screen copy removed."""

    blocked = blocked_text(shot)
    subject = scrub(shot.visual, blocked)
    if shot.generation_mode is GenerationMode.product_composite:
        subject = (
            f"{subject} The product is an unmarked stand-in volume. "
            "The real cutout is composited later."
        ).strip()
    elif _has_person(shot):
        subject = f"{subject} The person keeps the same face and clothes.".strip()
    elif any(ref.startswith("product:") for ref in shot.subject_refs):
        subject = f"{subject} The product keeps the same shape and color.".strip()
    if not subject:
        subject = "The subject from the storyboard, with no labels."
    if brand is not None and brand.tone:
        subject = f"{subject} Tone: {scrub(brand.tone, blocked)}."

    scene = _anchor_description(scene_anchors or [], shot.scene_ref)
    if not scene:
        scene = f"Scene {shot.scene_ref}, same layout and light in every shot of this place."
    scene = scrub(scene, blocked)

    style = _style_description(style_anchor)
    if not style and brief is not None and brief.style:
        style = brief.style
    if not style:
        style = "Steady commercial light, no decorative lettering."
    style = scrub(style, blocked)
    return subject, scene, style


def _has_person(shot: Shot) -> bool:
    return "人物" in shot.purpose or any(ref.startswith("person:") for ref in shot.subject_refs)


def _anchor_description(anchors: list[Any], ref: str) -> str:
    for item in anchors:
        item_ref = _field(item, "ref")
        if item_ref == ref:
            return _field(item, "description")
    return ""


def _style_description(anchor: Any | None) -> str:
    if anchor is None:
        return ""
    return _field(anchor, "description")


def _field(item: Any, name: str) -> str:
    if isinstance(item, dict):
        value = item.get(name, "")
    else:
        value = getattr(item, name, "")
    return value if isinstance(value, str) else ""
