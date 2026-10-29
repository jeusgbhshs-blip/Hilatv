"""Hook lines speed up. The ending CTA slows down and keeps a trailing pause."""

from __future__ import annotations

from dataclasses import dataclass

from workers.schemas.script import Script, ScriptSectionKind, Shot

HOOK_SPEED_FACTOR = 1.05
CTA_SPEED_FACTOR = 0.90
CTA_PAUSE_S = 0.4
SPEED_MIN = 0.2
SPEED_MAX = 3.0
DEFAULT_SPEED = 1.0
DEFAULT_VOICE = "zh_male_steady"


@dataclass(frozen=True)
class TakePlan:
    shot_id: str
    role: str
    speed: float
    pause_s: float


def clamp_speed(value: float) -> float:
    return round(min(SPEED_MAX, max(SPEED_MIN, value)), 4)


def plan_prosody(script: Script, base_speed: float) -> dict[str, TakePlan]:
    """One plan per shot. A shot that is both hook and ending CTA is treated as the CTA."""

    base = clamp_speed(base_speed if base_speed > 0 else DEFAULT_SPEED)
    roles = {shot.shot_id: _roles(shot, script) for shot in script.shots}
    ending = _ending_cta(script.shots, roles)
    plans: dict[str, TakePlan] = {}
    for shot in script.shots:
        kind = roles[shot.shot_id]
        if shot.shot_id == ending:
            plans[shot.shot_id] = TakePlan(
                shot.shot_id,
                "cta",
                clamp_speed(base * CTA_SPEED_FACTOR),
                CTA_PAUSE_S,
            )
            continue
        if "hook" in kind:
            plans[shot.shot_id] = TakePlan(
                shot.shot_id,
                "hook",
                clamp_speed(base * HOOK_SPEED_FACTOR),
                0.0,
            )
            continue
        if "cta" in kind:
            plans[shot.shot_id] = TakePlan(
                shot.shot_id,
                "cta",
                clamp_speed(base * CTA_SPEED_FACTOR),
                0.0,
            )
            continue
        plans[shot.shot_id] = TakePlan(shot.shot_id, "body", base, 0.0)
    return plans


def _roles(shot: Shot, script: Script) -> set[str]:
    found: set[str] = set()
    listed = False
    for section in script.sections:
        if shot.shot_id not in section.shot_ids:
            continue
        listed = True
        if section.kind is ScriptSectionKind.hook:
            found.add("hook")
        elif section.kind is ScriptSectionKind.cta:
            found.add("cta")
    if listed:
        return found
    if "钩子" in shot.purpose:
        found.add("hook")
    if "行动号召" in shot.purpose or shot.purpose.strip().upper() == "CTA":
        found.add("cta")
    return found


def _ending_cta(shots: list[Shot], roles: dict[str, set[str]]) -> str | None:
    ending: str | None = None
    for shot in shots:
        if "cta" in roles[shot.shot_id]:
            ending = shot.shot_id
    return ending
