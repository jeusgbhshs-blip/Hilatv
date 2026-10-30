"""N13 on a storyboard: line limits, alignment, and the product box."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.media_bytes import speech_timestamps
from workers.nodes.n13_subtitle.node import run
from workers.nodes.n13_subtitle.qa import QAError, check
from workers.nodes.n13_subtitle.schema import SubtitleCue
from workers.schemas.script import Script


def _shot(shot_id: str, order: int, text: str, duration: float) -> dict:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": duration,
        "purpose": "展示核心卖点",
        "visual": "柱塞泵特写，金属表面，画面里没有文字",
        "shot_size": "close_up",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop",
        "voiceover": text,
        "on_screen_text": [{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 1.2}],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def _take(shot_id: str, text: str, language: str, duration: float) -> dict:
    stamps, audio = speech_timestamps(text, language=language)
    return {
        "shot_id": shot_id,
        "uri": f"mock://{shot_id}",
        "voice": "zh_male_steady",
        "speed": 1.0,
        "pause_s": 0.0,
        "audio_s": audio,
        "hold_s": max(0.0, duration - audio),
        "duration_s": duration,
        "timestamps": stamps,
        "transcript": text,
        "cer": 0.0,
        "loudness_dbfs": -16.0,
        "clipped": False,
        "role": "body",
    }


def _request(
    tmp_path: Path,
    *,
    language: str,
    text: str,
    platforms: list[str],
    box: dict | None,
) -> dict:
    audio = speech_timestamps(text, language=language)[1]
    duration = max(2.0, round(audio + 0.2, 3))
    payload = {
        "script": {
            "script_id": "script-1",
            "brief_id": "brief-1",
            "language": language,
            "sections": [],
            "shots": [_shot("S01", 1, text, duration)],
        },
        "voiceovers": [_take("S01", text, language, duration)],
        "brief": {
            "brief_id": "brief-1",
            "raw_input": "给我们的柱塞泵做条片子",
            "goal": "获客",
            "platform": platforms,
            "duration_s": 15,
            "aspect_ratios": ["16:9"],
            "languages": [language],
            "video_type": "product_showcase",
            "audience": "采购",
            "must_include": ["30 MPa"],
            "style": "工业",
            "assumptions": [],
            "open_questions": [],
        },
        "subject_boxes": [box] if box else [],
        "width": 640,
        "height": 360,
        "work_dir": str(tmp_path),
    }
    return {"project_id": "p-n13", "payload": payload}


def test_node_writes_aligned_cues(tmp_path: Path) -> None:
    text = "这台高压柱塞泵以三十兆帕稳定运行，适合连续作业的工厂产线。"
    result = run(_request(tmp_path, language="zh", text=text, platforms=["抖音"], box=None))
    cues = check(result)
    assert cues
    assert all(cue.alignment_error_ms <= 100 for cue in cues)
    assert all(sum(1 for char in cue.text if not char.isspace()) <= 16 for cue in cues)
    assert any("柱塞泵" in cue.text for cue in cues)
    script = Script.model_validate(result.payload["script"])
    assert script.shots[0].on_screen_text[0].text == "30 MPa"
    assert (tmp_path / "subtitles.json").is_file()


def test_subject_conflict_lifts_the_cue(tmp_path: Path) -> None:
    text = "高压柱塞泵稳定运行。"
    plain = run(_request(tmp_path / "a", language="zh", text=text, platforms=["YouTube"], box=None))
    blocked = run(
        _request(
            tmp_path / "b",
            language="zh",
            text=text,
            platforms=["YouTube"],
            box={"shot_id": "S01", "x": 0.1, "y": 0.62, "w": 0.8, "h": 0.38},
        )
    )
    plain_y = SubtitleCue.model_validate(plain.payload["cues"][0]).y_ratio
    lifted_y = SubtitleCue.model_validate(blocked.payload["cues"][0]).y_ratio
    assert lifted_y < plain_y


def test_rerun_is_stable_and_input_is_checked(tmp_path: Path) -> None:
    text = "Built for 30 MPa every single day inside the workshop."
    raw = _request(tmp_path, language="en", text=text, platforms=["YouTube"], box=None)
    first = run(raw)
    second = run(raw)
    assert first.payload["cues"] == second.payload["cues"]
    assert all(len(SubtitleCue.model_validate(item).text) <= 42 for item in first.payload["cues"])
    with pytest.raises(ValidationError):
        run({"project_id": "p-n13", "payload": {}})
    with pytest.raises(TimeoutError):
        run(raw, timeout_s=0)
    with pytest.raises(ValueError):
        run(raw, max_attempts=0)


def test_qa_rejects_a_drifted_cue(tmp_path: Path) -> None:
    text = "高压柱塞泵稳定运行。"
    result = run(_request(tmp_path, language="zh", text=text, platforms=["YouTube"], box=None))
    cue = dict(result.payload["cues"][0])
    cue["audio_start_s"] = cue["audio_start_s"] + 0.25
    cue["alignment_error_ms"] = 250
    result.payload["cues"] = [cue]
    with pytest.raises(QAError):
        check(result)
