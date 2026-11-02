"""Quality check for N5. A failing storyboard is retried, not returned."""

from __future__ import annotations

from workers.nodes.n05_storyboard.modes import select_generation_mode
from workers.nodes.n05_storyboard.plan import NO_DRAWN, is_promo, shot_bounds
from workers.nodes.n05_storyboard.presets import load_presets
from workers.nodes.n05_storyboard.schema import N5Input, NodeResult
from workers.qa.copycheck import banned_for, banned_hits, invented_numbers
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script, Shot

_PRODUCT_SIZES = {"medium", "close_up"}


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> Script:
    if result.node != "n05_storyboard":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n05_storyboard result is not ok")
    brief, brand = _context(result)
    script = _script(result.payload.get("script"))
    try:
        duration = N5Input.model_validate(result.payload).story_duration_s
    except Exception as exc:
        raise QAError("invalid story duration") from exc
    if duration is not None and duration > brief.duration_s:
        raise QAError("story duration cannot exceed the requested whole film")
    audit_storyboard(script, brief, brand, duration_s=duration)
    return script


def audit_storyboard(
    script: Script, brief: Brief, brand: BrandKit | None, *, duration_s: float | None = None
) -> None:
    duration = brief.duration_s if duration_s is None else duration_s
    shots = script.shots
    if not shots:
        raise QAError("storyboard has no shots")
    for shot in shots:
        Shot.model_validate(shot.model_dump(mode="json"))
    total = sum(shot.duration_s for shot in shots)
    if duration <= 0 or abs(total - duration) / duration > 0.05:
        raise QAError(f"duration {total} is outside 5% of {duration}")
    if len(shots) > duration / 2:
        raise QAError("too many shots for the duration")
    _, _, lo, hi = shot_bounds(duration, promo=is_promo(brief))
    orders = [shot.order for shot in shots]
    if orders != list(range(1, len(shots) + 1)):
        raise QAError("shot order is not contiguous")
    preset_ids = {preset.id for preset in load_presets()}
    sizes = [shot.shot_size for shot in shots]
    for index in range(len(sizes) - 2):
        if sizes[index] == sizes[index + 1] == sizes[index + 2]:
            raise QAError("three identical shot sizes in a row")
    # 景别多元化：至少覆盖 3 种景别（远/全/中/近/特中的三种），短片的 1–2 镜除外。
    if len(sizes) >= 3 and len(set(sizes)) < 3:
        raise QAError("shot sizes are not diverse")
    seen_product = False
    banned = banned_for(brand)
    allowed = invented_source(brief, brand)
    for shot in shots:
        if shot.duration_s < lo - 1e-6 or shot.duration_s > hi + 1e-6:
            raise QAError(f"{shot.shot_id} duration {shot.duration_s} is outside {lo}-{hi}")
        if not shot.subject_refs and not shot.scene_ref:
            raise QAError(f"{shot.shot_id} has neither subject nor scene")
        if shot.camera not in preset_ids:
            raise QAError(f"{shot.shot_id} camera is not in the shot library")
        if NO_DRAWN not in shot.visual:
            raise QAError(f"{shot.shot_id} visual is missing the no-text constraint")
        expected = select_generation_mode(shot.purpose, brand)
        if shot.generation_mode is not expected:
            raise QAError(f"{shot.shot_id} mode {shot.generation_mode} != {expected}")
        if not seen_product and any(ref.startswith("product:") for ref in shot.subject_refs):
            if shot.shot_size not in _PRODUCT_SIZES:
                raise QAError("the product's first appearance must be a medium or close-up")
            seen_product = True
        _copy_ok(shot, banned, allowed)
        for card in shot.on_screen_text:
            if card.in_ > shot.duration_s + 1e-6 or card.out > shot.duration_s + 1e-6:
                raise QAError(f"{shot.shot_id} on-screen text runs past the shot")


def invented_source(brief: Brief, brand: BrandKit | None) -> set[str]:
    from workers.qa.copycheck import allowed_numbers

    return allowed_numbers(brief, brand)


def _copy_ok(shot: Shot, banned: list[str], allowed: set[str]) -> None:
    blob = "\n".join([shot.voiceover, shot.purpose, *[card.text for card in shot.on_screen_text]])
    hits = banned_hits(blob, banned)
    if hits:
        raise QAError(f"banned words in {shot.shot_id}: {hits[0]}")
    invented = invented_numbers(blob, allowed)
    if invented:
        raise QAError(f"invented numbers in {shot.shot_id}: {invented[0]}")


def _bounds(brief: Brief) -> tuple[int, int, float, float]:
    return shot_bounds(brief.duration_s, promo=is_promo(brief))


def _script(raw: object) -> Script:
    if not isinstance(raw, dict):
        raise QAError("n05_storyboard payload is missing script")
    try:
        return Script.model_validate(raw)
    except Exception as exc:
        raise QAError(f"script failed validation: {exc}") from exc


def _context(result: NodeResult) -> tuple[Brief, BrandKit | None]:
    raw_brief = result.payload.get("brief")
    if not isinstance(raw_brief, dict):
        raise QAError("n05_storyboard payload is missing brief")
    try:
        brief = Brief.model_validate(raw_brief)
    except Exception as exc:
        raise QAError(f"brief failed validation: {exc}") from exc
    raw_brand = result.payload.get("brand_kit")
    if raw_brand is None:
        return brief, None
    if not isinstance(raw_brand, dict):
        raise QAError("brand_kit must be an object or null")
    try:
        return brief, BrandKit.model_validate(raw_brand)
    except Exception as exc:
        raise QAError(f"brand kit failed validation: {exc}") from exc
