"""T08 acceptance: N8 keyframes and N10 clips for one storyboard.

No API key is required. The gateway in this script is the mock adapter with an
in-memory object store, so a missing MinIO does not matter.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from gateway.constants import NO_RENDERED_TEXT
from workers.media.trim import probe_duration_s
from workers.nodes.media_gateway import build_media_gateway
from workers.nodes.n04_script.node import run as run_script
from workers.nodes.n04_script.qa import check as check_script
from workers.nodes.n05_storyboard.node import run as run_board
from workers.nodes.n05_storyboard.qa import check as check_board
from workers.nodes.n08_keyframe.node import run as run_keyframes
from workers.nodes.n08_keyframe.qa import check as check_keyframes
from workers.nodes.n10_video.node import run as run_video
from workers.nodes.n10_video.qa import check as check_video
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode, Shot

FIXTURES = Path(__file__).resolve().parents[2] / "schemas" / "tests" / "fixtures"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="hilatv-t08-"))
    gateway = build_media_gateway(root)
    try:
        summary = run_chain(gateway)
    except Exception as exc:
        print(f"T08 accept: FAIL {exc}")
        return 1
    print(summary)
    return 0


def run_chain(gateway: Any) -> str:
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    scripted = run_script(
        {"project_id": "accept-t08", "payload": {"brief": brief, "brand_kit": brand}},
        gateway=gateway,
    )
    check_script(scripted)
    boarded = run_board(
        {
            "project_id": "accept-t08",
            "payload": {
                "brief": scripted.payload["brief"],
                "script": scripted.payload["script"],
                "brand_kit": scripted.payload["brand_kit"],
            },
        },
        gateway=gateway,
    )
    storyboard = check_board(boarded)
    frames = run_keyframes(
        {
            "project_id": "accept-t08",
            "payload": {
                "script": boarded.payload["script"],
                "brief": boarded.payload["brief"],
                "brand_kit": boarded.payload["brand_kit"],
            },
        },
        gateway=gateway,
    )
    keyframes = check_keyframes(frames)
    videos = run_video(
        {
            "project_id": "accept-t08",
            "payload": {
                "script": frames.payload["script"],
                "brief": frames.payload["brief"],
                "brand_kit": frames.payload["brand_kit"],
                "candidates": frames.payload["candidates"],
            },
        },
        gateway=gateway,
    )
    clips = check_video(videos)
    store = gateway.media_store
    shots = {shot.shot_id: shot for shot in storyboard.shots}
    _assert_coverage(shots, keyframes, clips, store)
    generative = [
        shot.shot_id
        for shot in storyboard.shots
        if shot.generation_mode is not GenerationMode.motion_graphics
    ]
    return (
        "T08 accept: "
        f"{len(storyboard.shots)} shots, {len(generative)} generative, "
        f"keyframes={len(keyframes)}, videos={len(clips)}, "
        "each generative shot has >= 3 candidates, prompts forbid rendered text, "
        "clips trimmed to duration_s with transition margin (mock)"
    )


def _assert_coverage(
    shots: dict[str, Shot],
    keyframes: list[Candidate],
    clips: list[Candidate],
    store: Any,
) -> None:
    for shot in shots.values():
        blocked = [card.text for card in shot.on_screen_text]
        stills = [row for row in keyframes if row.shot_id == shot.shot_id]
        videos = [row for row in clips if row.shot_id == shot.shot_id]
        if shot.generation_mode is GenerationMode.motion_graphics:
            if stills or videos:
                raise AssertionError(f"{shot.shot_id} should not be generated")
            continue
        opening = [row for row in stills if row.params.get("frame") == "first"]
        if len(opening) < 3 or len(videos) < 3:
            raise AssertionError(f"{shot.shot_id} has fewer than 3 candidates")
        if sum(row.selected for row in opening) != 1:
            raise AssertionError(f"{shot.shot_id} did not select one keyframe")
        if sum(row.selected for row in videos) != 1:
            raise AssertionError(f"{shot.shot_id} did not select one video")
        for row in [*stills, *videos]:
            prompt = str(row.params.get("prompt") or "")
            if NO_RENDERED_TEXT not in prompt:
                raise AssertionError(f"{row.candidate_id} missing no-text constraint")
            for text in blocked:
                if text and text in prompt:
                    raise AssertionError(f"{row.candidate_id} drew on-screen text")
            if not row.model or not row.uri or row.params.get("seed") is None:
                raise AssertionError(f"{row.candidate_id} is missing model, seed, or uri")
        for row in videos:
            if row.params.get("duration") not in (5, 10):
                raise AssertionError(f"{row.candidate_id} was not generated at 5 or 10 seconds")
            if float(row.params["head_margin_s"]) <= 0 or float(row.params["tail_margin_s"]) <= 0:
                raise AssertionError(f"{row.candidate_id} lost the transition margin")
            if row.params.get("trimmed") is not True:
                raise AssertionError(f"{row.candidate_id} was not trimmed")
            measured = probe_duration_s(store.get(row.uri))
            if abs(measured - shot.duration_s) > 0.25:
                raise AssertionError(f"{row.candidate_id} duration {measured} != {shot.duration_s}")
            if shot.generation_mode is GenerationMode.product_composite:
                if row.params.get("motion_strength") != "low":
                    raise AssertionError(f"{row.candidate_id} product motion is not low")


if __name__ == "__main__":
    raise SystemExit(main())
