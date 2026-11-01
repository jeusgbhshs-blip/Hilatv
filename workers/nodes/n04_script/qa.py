"""Quality check for N4. A failing script is retried, not returned."""

from __future__ import annotations

from workers.nodes.n04_script.schema import N4Input, NodeResult
from workers.qa.copycheck import (
    HOOK_SECONDS,
    banned_for,
    banned_hits,
    count_units,
    invented_numbers,
    phrase_is_sourced,
    spoken_seconds,
    target_units,
    within_target,
)
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script, ScriptSectionKind


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> Script:
    if result.node != "n04_script":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n04_script result is not ok")
    brief, brand = _context(result)
    try:
        duration = N4Input.model_validate(result.payload).story_duration_s
    except Exception as exc:
        raise QAError("invalid story duration") from exc
    if duration is not None and duration > brief.duration_s:
        raise QAError("story duration cannot exceed the requested whole film")
    primary = _script(result.payload.get("script"), "script")
    master = _script(result.payload.get("master"), "master")
    variants = result.payload.get("variants")
    if not isinstance(variants, list) or not variants:
        raise QAError("n04_script payload is missing variants")
    parsed = [_script(item, "variant") for item in variants]
    audit_script(primary, brief, brand, duration_s=duration)
    audit_script(master, brief, brand, duration_s=duration)
    if master.language.split("-", 1)[0].lower() != "zh":
        raise QAError("master script must be Chinese")
    for script in parsed:
        audit_script(script, brief, brand, duration_s=duration)
    languages = [script.language for script in parsed]
    if languages != list(brief.languages):
        raise QAError("variants do not follow brief.languages")
    if primary.language != brief.languages[0]:
        raise QAError("primary script language does not match the brief")
    return primary


def audit_script(
    script: Script, brief: Brief, brand: BrandKit | None, *, duration_s: float | None = None
) -> None:
    banned = banned_for(brand)
    allowed = _allowed(brief, brand)
    kinds = [section.kind for section in script.sections]
    if not kinds or kinds[0] is not ScriptSectionKind.hook:
        raise QAError("script must open with a hook")
    if kinds[-1] is not ScriptSectionKind.cta:
        raise QAError("script must end with a call to action")
    if ScriptSectionKind.proof not in kinds:
        raise QAError("script is missing proof")
    if kinds.count(ScriptSectionKind.hook) != 1:
        raise QAError("script must have one hook")
    if kinds.count(ScriptSectionKind.cta) != 1:
        raise QAError("script must have one call to action")
    if kinds.count(ScriptSectionKind.proof) != 1:
        raise QAError("script must have one proof section")
    selling = [
        section for section in script.sections if section.kind is ScriptSectionKind.selling_point
    ]
    if len(selling) > 3:
        raise QAError("a script has at most 3 selling points")
    proof_at = kinds.index(ScriptSectionKind.proof)
    late = [
        index
        for index, kind in enumerate(kinds)
        if kind is ScriptSectionKind.selling_point and index > proof_at
    ]
    if late:
        raise QAError("selling points must come before proof")
    blob = "\n".join(section.text for section in script.sections)
    hits = banned_hits(blob, banned)
    if hits:
        raise QAError(f"banned words in script: {hits[0]}")
    invented = invented_numbers(blob, allowed)
    if invented:
        raise QAError(f"invented numbers in script: {invented[0]}")
    hook = script.sections[0]
    if spoken_seconds(hook.text, script.language) > HOOK_SECONDS + 1e-9:
        raise QAError("hook is not inside the first 3 seconds")
    total = sum(count_units(section.text, script.language) for section in script.sections)
    target = target_units(brief.duration_s if duration_s is None else duration_s, script.language)
    if not within_target(total, target):
        raise QAError(f"word count {total} is outside 5% of {target:.2f}")
    sources = _point_sources(brief, brand)
    for section in selling:
        if not phrase_is_sourced(section.text, sources):
            raise QAError("selling point is not in the brand kit or the user input")


def _script(raw: object, label: str) -> Script:
    if not isinstance(raw, dict):
        raise QAError(f"n04_script payload is missing {label}")
    try:
        return Script.model_validate(raw)
    except Exception as exc:
        raise QAError(f"{label} failed validation: {exc}") from exc


def _context(result: NodeResult) -> tuple[Brief, BrandKit | None]:
    raw_brief = result.payload.get("brief")
    if not isinstance(raw_brief, dict):
        raise QAError("n04_script payload is missing brief")
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


def _allowed(brief: Brief, brand: BrandKit | None) -> set[str]:
    from workers.qa.copycheck import allowed_numbers

    return allowed_numbers(brief, brand)


def _point_sources(brief: Brief, brand: BrandKit | None) -> list[str]:
    sources = [brief.raw_input, *brief.must_include, brief.goal, brief.audience]
    if brand is not None:
        sources.append(brand.company_name)
        for product in brand.products:
            sources.append(product.name)
            sources.extend(product.selling_points)
            sources.extend(product.forbidden_changes)
    return [item for item in sources if item]
