"""N12: licensed beds, beat alignment, and a blocked delivery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gateway.adapters.mock_adapter import MockAdapter
from gateway.media_bytes import render_beat_wav
from gateway.models import Invocation
from workers.nodes.n12_music.accept import evaluate
from workers.nodes.n12_music.library import match_sfx, select_track
from workers.nodes.n12_music.node import run
from workers.nodes.n12_music.qa import QAError
from workers.nodes.n12_music.schema import LicenseRecord, incomplete_reason
from workers.schemas.script import Shot


def test_library_picks_mood_and_shot_tags() -> None:
    assert select_track("稳重、低沉").bpm == 90
    assert select_track("轻快鼓点").library_id == "hilatv-self-made-pulse"
    product = _bare_shot("产品落地特写", "close_up", "cut")
    factory = _bare_shot("车间机械运转", "wide", "cut")
    dissolve = _bare_shot("空镜", "wide", "dissolve")
    assert match_sfx(product) == "impact"
    assert match_sfx(factory) == "machine"
    assert match_sfx(dissolve) == "whoosh"


def test_incomplete_license_blocks() -> None:
    reason = incomplete_reason(
        [LicenseRecord(record_id="music-bed", kind="music", source="lib", license="")]
    )
    assert "license" in reason


def test_mock_music_echoes_the_test_library_license() -> None:
    call = Invocation(
        task="music",
        prompt="instrumental",
        model="mock-music",
        provider="mock",
        seed=3,
        params={
            "duration_s": 2,
            "bpm": 90,
            "source": "hilatv-test-library/hilatv-self-made-steady",
            "license": "CC0-1.0",
            "library_id": "hilatv-self-made-steady",
        },
    )
    output = MockAdapter().invoke(call).output
    assert output["license"] == "CC0-1.0"
    assert output["source"].startswith("hilatv-test-library/")
    assert output["bpm"] == 90
    assert output["duration_s"] == 2
    wav = render_beat_wav(duration_s=1.0, bpm=90, seed=3)
    assert wav.startswith(b"RIFF")


def test_live_mode_rejects_the_test_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))

    class _LiveMock:
        def music(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            del prompt, kwargs
            return {
                "mock": True,
                "source": "hilatv-test-library/steady",
                "license": "CC0-1.0",
                "bpm": 90,
                "duration_s": 2,
            }

    from workers.nodes.n12_music.accept import fixture

    with pytest.raises(QAError, match="test-library"):
        run(
            {
                "project_id": "live-block",
                "payload": {**fixture(), "work_dir": str(tmp_path / "n12")},
            },
            gateway=_LiveMock(),
            max_attempts=1,
        )


def test_work_dir_must_stay_inside_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir()

    class _Gateway:
        def music(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            del prompt, kwargs
            return {
                "mock": True,
                "source": "hilatv-test-library/steady",
                "license": "CC0-1.0",
                "bpm": 90,
                "duration_s": 2,
            }

    from workers.nodes.n12_music.accept import fixture

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(QAError, match="project directory"):
        run(
            {"project_id": "path-block", "payload": {**fixture(), "work_dir": str(outside)}},
            gateway=_Gateway(),
            max_attempts=1,
        )


def test_missing_license_does_not_deliver(tmp_path: Path) -> None:
    class Blank:
        def music(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            del prompt, kwargs
            return {"source": "orphan", "license": "  ", "bpm": 100}

    from workers.nodes.n12_music.accept import fixture

    with pytest.raises(QAError, match="license"):
        run(
            {"project_id": "block", "payload": {**fixture(), "work_dir": str(tmp_path)}},
            gateway=Blank(),
            max_attempts=1,
        )


def test_rendered_mix_meets_the_spec(tmp_path: Path) -> None:
    from gateway.tests.conftest import build_gateway, mock_llm_routes

    gateway_dir = tmp_path / "gw"
    gateway_dir.mkdir()
    gateway = build_gateway(gateway_dir, routes=mock_llm_routes())
    seen: list[str] = []

    class Recording:
        def music(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            seen.append(prompt)
            return gateway.music(prompt, **kwargs)

    metrics = evaluate(tmp_path / "mix", Recording())
    assert metrics["picture_cut_alignment"] == "未达标"
    assert 10 <= metrics["ducking_db"] <= 12
    assert abs(metrics["narration_lufs"] + 16) <= 1
    assert abs(metrics["mix_lufs"] + 14) <= 1
    assert abs(metrics["mp4_lufs"] + 14) <= 1
    assert seen and "无歌词" in seen[0] and "无文字" in seen[0]
    assert gateway.store.list_logs()[-1]["task"] == "music"


def _bare_shot(visual: str, size: str, transition: str) -> Shot:
    return Shot.model_validate(
        {
            "shot_id": "S01",
            "order": 1,
            "duration_s": 2,
            "purpose": visual,
            "visual": visual,
            "shot_size": size,
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": "",
            "on_screen_text": [],
            "transition_out": transition,
            "generation_mode": "image_to_video",
            "status": "pending",
        }
    )
