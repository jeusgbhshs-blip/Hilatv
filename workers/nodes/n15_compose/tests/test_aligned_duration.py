"""Picture, subtitles, and packaging share N12's shot durations."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from workers.nodes.n15_compose.align import apply_aligned_script
from workers.nodes.n15_compose.node import run
from workers.nodes.n15_compose.qa import QAError
from workers.nodes.n15_compose.schema import N15Input


def test_mismatched_shots_are_refused() -> None:
    raw = _request([("S01", 1.0)], [("S99", 1.5)])
    payload = N15Input.model_validate(raw)
    with pytest.raises(QAError, match="do not match"):
        apply_aligned_script(payload, intro_s=0.0)


def test_timeline_moves_picture_subtitles_and_packaging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
    raw = _request([("S01", 1.0), ("S02", 1.0)], [("S01", 1.5), ("S02", 1.5)])
    raw.update(
        {
            "work_dir": str(tmp_path / "n15"),
            "width": 320,
            "height": 180,
            "intro_s": 0,
            "outro_s": 0.4,
            "cues": [
                {
                    "cue_id": "c1",
                    "shot_id": "S02",
                    "text": "第二句",
                    "lines": ["第二句"],
                    "start_s": 1.2,
                    "end_s": 1.5,
                    "audio_start_s": 0.2,
                    "audio_end_s": 0.5,
                    "alignment_error_ms": 0,
                    "x_ratio": 0.1,
                    "y_ratio": 0.7,
                    "highlights": [],
                    "language": "zh",
                }
            ],
            "elements": [
                _element("badge", "badge", "30 MPa", 0.0, 1.0, "topleft", logo),
                _element("corner", "corner_logo", "", 0.0, 2.0, "topleft", logo),
                _element("outro-logo", "outro_logo", "", 2.0, 2.4, "center", logo),
                _element("outro-cta", "outro_cta", "联系我们", 2.0, 2.4, "center", logo),
            ],
        }
    )
    result = run({"project_id": "aligned", "payload": raw}, max_attempts=1)
    timeline = result.payload["timeline"]
    clips = {item["clip_id"]: item for item in timeline["clips"]}
    assert clips["S01"]["duration_s"] == 1.5
    assert clips["S01"]["start_s"] == 0
    assert clips["S02"]["start_s"] == 1.5
    assert abs(clips["outro"]["start_s"] - 3.0) < 1e-3
    overlays = timeline["overlays"]
    subtitle = next(item for item in overlays if item["text"] == "第二句")
    assert abs(subtitle["start_s"] - 1.7) < 1e-3
    badge = next(item for item in overlays if item["kind"] == "badge")
    assert abs(badge["end_s"] - 1.5) < 1e-3
    corner = next(item for item in overlays if item["kind"] == "corner_logo")
    assert abs(corner["end_s"] - 3.0) < 1e-3
    outro = next(item for item in overlays if item["kind"] == "outro_logo")
    assert abs(outro["start_s"] - 3.0) < 1e-3
    labels = [item for item in overlays if item["kind"] == "ai_label"]
    assert len(labels) == 1
    assert labels[0]["text"] == "AI生成"
    assert labels[0]["start_s"] == 0
    assert result.payload["script"]["shots"][0]["duration_s"] == 1.5


def _request(shots: list[tuple[str, float]], aligned: list[tuple[str, float]]) -> dict[str, object]:
    return {
        "script": _script(shots),
        "aligned_script": _script(aligned),
    }


def _script(shots: list[tuple[str, float]]) -> dict[str, object]:
    return {
        "script_id": "script-align",
        "brief_id": "brief-align",
        "language": "zh",
        "sections": [],
        "shots": [
            _shot(shot_id, order, duration)
            for order, (shot_id, duration) in enumerate(shots, start=1)
        ],
    }


def _shot(shot_id: str, order: int, duration: float) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": duration,
        "purpose": "产品特写",
        "visual": "金属泵体，画面里没有文字",
        "shot_size": "close_up",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop",
        "voiceover": "",
        "on_screen_text": [],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def _element(
    element_id: str,
    kind: str,
    text: str,
    start_s: float,
    end_s: float,
    anchor: str,
    logo: Path,
) -> dict[str, object]:
    return {
        "element_id": element_id,
        "kind": kind,
        "text": text,
        "start_s": start_s,
        "end_s": end_s,
        "anchor": anchor,
        "y_ratio": 0.4,
        "png_path": str(logo),
    }
