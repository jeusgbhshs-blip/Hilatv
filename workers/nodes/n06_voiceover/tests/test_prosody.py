"""Hook lines are 5% faster. The last CTA slows down and keeps a pause."""

from __future__ import annotations

from workers.nodes.n06_voiceover.prosody import (
    CTA_PAUSE_S,
    CTA_SPEED_FACTOR,
    HOOK_SPEED_FACTOR,
    plan_prosody,
)
from workers.nodes.n06_voiceover.tests.test_node import _request
from workers.schemas.script import Script


def test_hook_speeds_up_and_ending_cta_pauses() -> None:
    script = Script.model_validate(_request()["payload"]["script"])
    plans = plan_prosody(script, 1.0)
    assert plans["S01"].role == "hook"
    assert plans["S01"].speed == round(HOOK_SPEED_FACTOR, 4)
    assert plans["S01"].pause_s == 0
    assert plans["S02"].role == "body"
    assert plans["S02"].speed == 1.0
    assert plans["S02"].pause_s == 0
    assert plans["S03"].role == "cta"
    assert plans["S03"].speed == round(CTA_SPEED_FACTOR, 4)
    assert plans["S03"].pause_s == CTA_PAUSE_S


def test_brand_speed_scales_both_ends() -> None:
    script = Script.model_validate(_request()["payload"]["script"])
    plans = plan_prosody(script, 1.2)
    assert plans["S01"].speed == round(1.2 * HOOK_SPEED_FACTOR, 4)
    assert plans["S03"].speed == round(1.2 * CTA_SPEED_FACTOR, 4)


def test_single_shot_that_is_also_the_cta_slows_down() -> None:
    raw = _request()["payload"]["script"]
    raw["shots"] = [raw["shots"][0] | {"shot_id": "S01", "purpose": "钩子"}]
    raw["sections"] = [
        {"kind": "hook", "text": raw["shots"][0]["voiceover"], "shot_ids": ["S01"]},
        {"kind": "cta", "text": raw["shots"][0]["voiceover"], "shot_ids": ["S01"]},
    ]
    plans = plan_prosody(Script.model_validate(raw), 1.0)
    assert plans["S01"].role == "cta"
    assert plans["S01"].pause_s == CTA_PAUSE_S
    assert plans["S01"].speed == round(CTA_SPEED_FACTOR, 4)
