"""A short marked master shared by the unit test and ``make accept-t17``."""

from __future__ import annotations

import json
from pathlib import Path

from workers.nodes.n17_deliver.plate import encode_marked_master
from workers.nodes.n17_deliver.schema import SubjectTrack

_ROOT = Path(__file__).resolve().parents[3]
_BRIEF = _ROOT / "workers" / "schemas" / "tests" / "fixtures" / "brief.json"
_BRAND = _ROOT / "workers" / "schemas" / "tests" / "fixtures" / "brand_kit.json"


def storyboard() -> tuple[
    dict[str, object],
    dict[str, object],
    list[SubjectTrack],
    tuple[float, float],
]:
    brief = json.loads(_BRIEF.read_text(encoding="utf-8"))
    brief.update(
        {
            "duration_s": 5,
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "languages": ["zh", "en"],
            "platform": ["抖音", "YouTube"],
        }
    )
    durations = (1.0, 1.0)
    tracks = [
        SubjectTrack(shot_id="S01", x=0.12, y=0.28, w=0.16, h=0.38, x_end=0.52, y_end=0.30),
        SubjectTrack(shot_id="S02", x=0.06, y=0.32, w=0.84, h=0.28),
    ]
    shots = [
        _shot("S01", 1, durations[0], "先看这台柱塞泵"),
        _shot("S02", 2, durations[1], "按资料说明压力"),
    ]
    script = {
        "script_id": "script-zh",
        "brief_id": brief["brief_id"],
        "language": "zh",
        "sections": [],
        "shots": shots,
    }
    return script, brief, tracks, durations


def acceptance_request(
    root: Path,
    *,
    project_id: str = "accept-t17",
    languages: list[str] | None = None,
    aspect_ratios: list[str] | None = None,
    regenerate_vertical: bool = False,
    long_edge: int = 320,
    with_tracks: bool = True,
) -> dict[str, object]:
    """Two shots inside ``root/project_id``. The master is not a client path.

    ``HILATV_PROJECT_DIR`` must be ``root`` before the node runs.
    """

    project = root / project_id
    project.mkdir(parents=True, exist_ok=True)
    width, height = 320, 180
    script, brief, tracks, durations = storyboard()
    segments: list[tuple[float, float, SubjectTrack]] = []
    cursor = 0.0
    for duration, track in zip(durations, tracks, strict=True):
        segments.append((cursor, duration, track))
        cursor += duration
    master = project / "master.mp4"
    encode_marked_master(master, width=width, height=height, segments=segments)
    brand = json.loads(_BRAND.read_text(encoding="utf-8"))
    return {
        "project_id": project_id,
        "payload": {
            "script": script,
            "brief": brief,
            "brand_kit": brand,
            "master_path": str(master),
            "subject_tracks": [item.model_dump(mode="json") for item in tracks]
            if with_tracks
            else [],
            "aspect_ratios": aspect_ratios or ["16:9", "9:16", "1:1"],
            "languages": languages or ["zh", "en"],
            "durations_s": [5],
            "long_edge": long_edge,
            "regenerate_vertical": regenerate_vertical,
            "work_dir": str(project / "out"),
        },
    }


def _shot(shot_id: str, order: int, duration: float, voice: str) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": duration,
        "purpose": "展示产品",
        "visual": "金属泵体在车间冷光下，画面里没有文字",
        "shot_size": "close_up",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop",
        "voiceover": voice,
        "on_screen_text": [
            {"text": "30MPa", "style": "spec_badge", "in": 0.1, "out": max(0.2, duration - 0.1)}
        ],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }
