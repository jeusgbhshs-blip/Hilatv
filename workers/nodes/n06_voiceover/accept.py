"""T07 acceptance: N6 on fixture storyboards, mock TTS, no API key.

The storyboard stays within 5% of the Brief. Every shot is at least as long
as its voiceover, including the CTA pause. Spare time is picture hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers.nodes.n04_script.node import run as run_script
from workers.nodes.n05_storyboard.node import run as run_board
from workers.nodes.n06_voiceover.node import run as run_voice
from workers.nodes.n06_voiceover.prosody import CTA_PAUSE_S, HOOK_SPEED_FACTOR, plan_prosody
from workers.nodes.n06_voiceover.qa import check
from workers.nodes.n06_voiceover.timing import DURATION_TOLERANCE, boosted_speed
from workers.schemas.brief import Brief
from workers.schemas.script import Script

FIXTURES = Path(__file__).resolve().parents[2] / "schemas" / "tests" / "fixtures"


def main() -> int:
    from gateway import get_gateway, reset_gateway

    reset_gateway()
    gateway = get_gateway()
    failures = run_suite(gateway)
    if failures:
        print(f"T07 accept: FAIL {len(failures)}")
        for item in failures:
            print(f"[fail] {item}")
        return 1
    print("T07 accept: storyboard within 5% of the brief, each shot duration >= its audio (mock)")
    return 0


def run_suite(gateway: Any) -> list[str]:
    failures: list[str] = []
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    cases: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
        ("spec-en-30", brief, brand),
        ("zh-5-promo", _copy(brief, duration_s=5, languages=["zh"]), brand),
        (
            "zh-15-short",
            _copy(
                brief,
                duration_s=15,
                languages=["zh"],
                video_type="sku_clip",
                raw_input="给这款杯子做15秒带货短视频",
                must_include=["杯身 300ml"],
            ),
            None,
        ),
    ]
    for label, brief_raw, brand_raw in cases:
        try:
            _case(gateway, label, brief_raw, brand_raw)
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            print(f"[fail] {label}: {exc}")
    return failures


def _case(
    gateway: Any,
    label: str,
    brief_raw: dict[str, Any],
    brand_raw: dict[str, Any] | None,
) -> None:
    scripted = run_script(
        {"project_id": "accept-t07", "payload": {"brief": brief_raw, "brand_kit": brand_raw}},
        gateway=gateway,
    )
    boarded = run_board(
        {
            "project_id": "accept-t07",
            "payload": {
                "brief": scripted.payload["brief"],
                "script": scripted.payload["script"],
                "brand_kit": scripted.payload["brand_kit"],
            },
        },
        gateway=gateway,
    )
    voiced = run_voice(
        {
            "project_id": "accept-t07",
            "payload": {
                "script": boarded.payload["script"],
                "brief": boarded.payload["brief"],
                "brand_kit": boarded.payload["brand_kit"],
            },
        },
        gateway=gateway,
    )
    script = check(voiced)
    brief = Brief.model_validate(scripted.payload["brief"])
    _alignment(script, voiced.payload, brief.duration_s, brand_raw)
    _prosody(script, brand_raw)
    audio = float(voiced.payload["audio_duration_s"])
    board = float(voiced.payload["storyboard_duration_s"])
    error = abs(board - brief.duration_s) / brief.duration_s
    print(
        f"[ok] {label} lang={script.language} shots={len(script.shots)} "
        f"audio={audio:.3f}s board={board:.3f}s brief={brief.duration_s}s "
        f"error={error:.2%}"
    )


def _alignment(
    script: Script,
    payload: dict[str, Any],
    brief_s: float,
    brand_raw: dict[str, Any] | None,
) -> None:
    takes = {item["shot_id"]: item for item in payload["voiceovers"]}
    board = sum(shot.duration_s for shot in script.shots)
    if brief_s <= 0 or abs(board - brief_s) / brief_s > DURATION_TOLERANCE:
        raise AssertionError(f"storyboard {board} is outside 5% of brief {brief_s}")
    base = 1.0 if brand_raw is None else float(brand_raw["voice"]["speed"])
    plans = plan_prosody(script, base)
    factor = float(payload.get("speed_factor") or 1)
    for shot in script.shots:
        if not shot.voiceover.strip():
            continue
        take = takes[shot.shot_id]
        if shot.duration_s + 1e-3 < float(take["audio_s"]):
            raise AssertionError(f"{shot.shot_id} is shorter than its audio")
        if abs(shot.duration_s - float(take["duration_s"])) > 0.001:
            raise AssertionError(f"{shot.shot_id} timeline does not match the shot")
        expected = boosted_speed(plans[shot.shot_id].speed, factor)
        if abs(float(take["speed"]) - expected) > 1e-3:
            raise AssertionError(f"{shot.shot_id} speed {take['speed']} != {expected}")
        if float(take["cer"]) >= 0.02:
            raise AssertionError(f"{shot.shot_id} cer {take['cer']}")
        if take["clipped"]:
            raise AssertionError(f"{shot.shot_id} clipped")


def _prosody(script: Script, brand_raw: dict[str, Any] | None) -> None:
    base = 1.0
    if brand_raw is not None:
        base = float(brand_raw["voice"]["speed"])
    plans = plan_prosody(script, base)
    hooks = [plan for plan in plans.values() if plan.role == "hook"]
    endings = [plan for plan in plans.values() if plan.role == "cta" and plan.pause_s > 0]
    if not endings:
        raise AssertionError("storyboard has no ending CTA pause")
    if hooks:
        expected = round(min(3.0, max(0.2, base * HOOK_SPEED_FACTOR)), 4)
        if any(abs(plan.speed - expected) > 1e-4 for plan in hooks):
            raise AssertionError(f"hook speed is not {expected}")
    elif len(script.shots) > 1:
        raise AssertionError("storyboard has no hook line")
    if any(abs(plan.pause_s - CTA_PAUSE_S) > 1e-4 for plan in endings):
        raise AssertionError("ending CTA pause is missing")


def _copy(brief: dict[str, Any], **updates: Any) -> dict[str, Any]:
    copied = json.loads(json.dumps(brief))
    copied.update(updates)
    return copied


if __name__ == "__main__":
    raise SystemExit(main())
