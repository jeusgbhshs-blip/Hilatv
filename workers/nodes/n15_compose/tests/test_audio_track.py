"""N15 takes an optional soundtrack and refuses one that has no license."""

from __future__ import annotations

import array
import wave
from pathlib import Path

import pytest
from PIL import Image

from workers.nodes.n15_compose.node import run
from workers.nodes.n15_compose.qa import QAError, check


def test_missing_license_blocks_before_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    wav = tmp_path / "mix.wav"
    _tone(wav)
    with pytest.raises(QAError, match="license"):
        run(
            {
                "project_id": "n15-block",
                "payload": {
                    **_payload(tmp_path),
                    "audio_track": {
                        "path": str(wav),
                        "duration_s": 0.4,
                        "source": "",
                        "license": "",
                    },
                },
            },
            max_attempts=1,
        )


def test_track_outside_the_project_is_refused(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(project))
    wav = tmp_path / "mix.wav"
    _tone(wav)
    with pytest.raises(QAError, match="project directory"):
        run(
            {
                "project_id": "n15-escape",
                "payload": {
                    **_payload(project),
                    "audio_track": {
                        "path": str(wav),
                        "duration_s": 0.4,
                        "source": "hilatv-test-library/steady",
                        "license": "CC0-1.0",
                    },
                },
            },
            max_attempts=1,
        )


def test_licensed_track_is_the_timeline_audio(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    wav = tmp_path / "mix.wav"
    _tone(wav)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
    result = run(
        {
            "project_id": "n15-track",
            "payload": {
                **_payload(tmp_path),
                "audio_track": {
                    "path": str(wav),
                    "duration_s": 0.4,
                    "source": "hilatv-test-library/steady",
                    "license": "CC0-1.0",
                },
                "licenses": [
                    {
                        "record_id": "music-bed",
                        "kind": "music",
                        "source": "hilatv-test-library/steady",
                        "license": "CC0-1.0",
                        "title": "Steady bed",
                    }
                ],
                "elements": [
                    {
                        "element_id": "outro-logo",
                        "kind": "outro_logo",
                        "text": "",
                        "start_s": 0.5,
                        "end_s": 0.9,
                        "anchor": "center",
                        "y_ratio": 0.4,
                        "png_path": str(logo),
                    },
                    {
                        "element_id": "outro-cta",
                        "kind": "outro_cta",
                        "text": "联系我们",
                        "start_s": 0.5,
                        "end_s": 0.9,
                        "anchor": "center",
                        "y_ratio": 0.6,
                        "png_path": str(logo),
                    },
                ],
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    timeline = check(result)
    assert [clip.path for clip in timeline.audio] == [str(wav)]
    assert result.payload["audio_track"]["license"] == "CC0-1.0"


def _payload(tmp_path: Path) -> dict:
    return {
        "work_dir": str(tmp_path / "edit"),
        "intro_s": 0,
        "outro_s": 0.4,
        "width": 320,
        "height": 180,
        "script": {
            "script_id": "script-1",
            "brief_id": "brief-1",
            "language": "zh",
            "sections": [],
            "shots": [
                {
                    "shot_id": "S01",
                    "order": 1,
                    "duration_s": 0.5,
                    "purpose": "卖点",
                    "visual": "柱塞泵，没有文字",
                    "shot_size": "medium",
                    "camera": "locked_off",
                    "subject_refs": ["product:HP-300"],
                    "scene_ref": "scene:workshop",
                    "voiceover": "",
                    "on_screen_text": [],
                    "transition_out": "cut",
                    "generation_mode": "image_to_video",
                    "status": "pending",
                }
            ],
        },
    }


def _tone(path: Path) -> None:
    rate = 48000
    frames = rate // 2
    samples = array.array("h", [0] * frames)
    for index in range(frames):
        samples[index] = int(4000 * (index % 32) / 32)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
