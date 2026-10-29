"""N6 writes durations from mock TTS and passes speed and pause into the call."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from workers.nodes.n06_voiceover import node as node_mod
from workers.nodes.n06_voiceover.audio import FRAME_S
from workers.nodes.n06_voiceover.node import run
from workers.nodes.n06_voiceover.qa import QAError, check
from workers.nodes.n06_voiceover.schema import NodeResult
from workers.schemas.asset import AssetKind
from workers.schemas.script import Script

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _shot(
    shot_id: str,
    order: int,
    purpose: str,
    voiceover: str,
    *,
    cards: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": 4.0,
        "purpose": purpose,
        "visual": "产品中近景，画面无任何文字、无 Logo、无价格、无电话号码。",
        "shot_size": "medium",
        "camera": "slow_push_in",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop_01",
        "voiceover": voiceover,
        "on_screen_text": cards
        or [{"text": "30 MPa", "style": "spec_badge", "in": 0.4, "out": 3.6}],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def _request() -> dict[str, Any]:
    hook = "压力不够怎么办"
    point = "柱塞泵压力三十兆帕"
    cta = "欢迎来厂看设备"
    return {
        "project_id": "proj-n6",
        "payload": {
            "script": {
                "script_id": "script-1",
                "brief_id": "brief-1",
                "language": "zh",
                "sections": [
                    {"kind": "hook", "text": hook, "shot_ids": ["S01"]},
                    {"kind": "selling_point", "text": point, "shot_ids": ["S02"]},
                    {"kind": "cta", "text": cta, "shot_ids": ["S03"]},
                ],
                "shots": [
                    _shot("S01", 1, "钩子", hook),
                    _shot("S02", 2, "卖点", point),
                    _shot("S03", 3, "行动号召", cta, cards=[]),
                ],
            },
            "brand_kit": None,
            "brief": None,
        },
    }


def test_durations_follow_the_audio(gateway) -> None:
    result = run(_request(), gateway=gateway)
    script = check(result)
    assert isinstance(script, Script)
    takes = {item["shot_id"]: item for item in result.payload["voiceovers"]}
    assert takes["S01"]["speed"] == 1.05
    assert takes["S01"]["pause_s"] == 0
    assert takes["S01"]["role"] == "hook"
    assert takes["S02"]["speed"] == 1.0
    assert "柱塞泵" in takes["S02"]["lexicon"]
    assert "柱塞" not in takes["S02"]["lexicon"]
    assert takes["S03"]["speed"] == 0.9
    assert takes["S03"]["pause_s"] == 0.4
    assert takes["S03"]["role"] == "cta"
    audio = 0.0
    for shot in script.shots:
        take = takes[shot.shot_id]
        assert abs(shot.duration_s - take["duration_s"]) <= 0.001
        assert shot.duration_s + 1e-3 >= take["audio_s"]
        assert take["hold_s"] == 0
        assert shot.duration_s != 4.0
        assert take["cer"] < 0.02
        assert take["clipped"] is False
        audio += take["duration_s"]
        for card in shot.on_screen_text:
            assert 0 <= card.in_ <= card.out <= shot.duration_s + 1e-6
    assert abs(audio - sum(shot.duration_s for shot in script.shots)) <= FRAME_S
    assets = result.payload["assets"]
    assert len(assets) == 3
    assert all(item["kind"] == AssetKind.voiceover.value for item in assets)
    again = run(_request(), gateway=gateway)
    assert again.payload["script"] == result.payload["script"]
    assert again.payload["assets"] == result.payload["assets"]
    tasks = {row["task"] for row in gateway.store.list_logs(project_id="proj-n6")}
    assert tasks <= {"tts", "asr"}
    assert "tts" in tasks and "asr" in tasks


def test_speed_and_pause_are_the_tts_arguments(gateway) -> None:
    seen: list[dict[str, Any]] = []
    original = gateway.tts

    def spy(text: str, **kwargs: Any) -> dict[str, Any]:
        seen.append({"text": text, "params": kwargs.get("params")})
        return original(text, **kwargs)

    gateway.tts = spy
    run(_request(), gateway=gateway)
    by_text = {item["text"]: item["params"] for item in seen}
    assert by_text["压力不够怎么办"]["speed"] == 1.05
    assert by_text["压力不够怎么办"]["pause_s"] == 0
    assert by_text["欢迎来厂看设备"]["speed"] == 0.9
    assert by_text["欢迎来厂看设备"]["pause_s"] == 0.4
    assert by_text["柱塞泵压力三十兆帕"]["lexicon"][0]["text"] == "柱塞泵"
    assert all("0532" not in item["text"] for item in seen)


def test_phone_on_the_card_is_not_added_to_speech(gateway) -> None:
    raw = _request()
    raw["payload"]["script"]["shots"][2]["on_screen_text"] = [
        {"text": "0532-88880000", "style": "cta_line", "in": 0.2, "out": 3.8}
    ]
    seen: list[str] = []
    original = gateway.tts

    def spy(text: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(text)
        return original(text, **kwargs)

    gateway.tts = spy
    result = run(raw, gateway=gateway)
    check(result)
    assert "0532-88880000" not in seen
    assert seen[-1] == "欢迎来厂看设备"


def test_high_error_rate_fails(gateway) -> None:
    original = gateway.asr

    def wrong(uri: str, **kwargs: Any) -> dict[str, Any]:
        out = dict(original(uri, **kwargs))
        out["text"] = "完全不对"
        return out

    gateway.asr = wrong
    with pytest.raises(QAError, match="character error rate"):
        run(_request(), gateway=gateway, max_attempts=1)


def test_retry_accepts_the_next_transcript(gateway) -> None:
    state = {"n": 0}
    original = gateway.asr

    def flaky(uri: str, **kwargs: Any) -> dict[str, Any]:
        state["n"] += 1
        out = dict(original(uri, **kwargs))
        if state["n"] == 1:
            out["text"] = "完全不对"
        return out

    gateway.asr = flaky
    result = run(_request(), gateway=gateway, max_attempts=2)
    assert isinstance(result, NodeResult)
    assert result.attempt == 2


def test_clipped_wav_fails_the_node(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    from workers.nodes.n06_voiceover.tests.test_audio import _tone, _wav

    planted = _wav([32767] * 400 + _tone())

    def fake_load(*_args: object, **_kwargs: object) -> bytes:
        return planted

    monkeypatch.setattr(node_mod, "load_take", fake_load)
    with pytest.raises(QAError, match="clipped"):
        run(_request(), gateway=gateway, max_attempts=1)


def test_short_read_pads_to_the_brief(gateway) -> None:
    raw = _request()
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brief["duration_s"] = 30
    brief["languages"] = ["zh"]
    raw["payload"]["brief"] = brief
    result = run(raw, gateway=gateway)
    script = check(result)
    total = sum(shot.duration_s for shot in script.shots)
    assert abs(total - 30) / 30 <= 0.05
    assert result.payload["speed_factor"] == 1.0
    takes = {item["shot_id"]: item for item in result.payload["voiceovers"]}
    assert sum(item["hold_s"] for item in takes.values()) > 0
    for shot in script.shots:
        take = takes[shot.shot_id]
        assert shot.duration_s + 1e-3 >= take["audio_s"]
        assert take["audio_s"] < 30


def test_overlong_copy_is_flagged_for_the_script(gateway) -> None:
    raw = _request()
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brief["duration_s"] = 10
    brief["languages"] = ["zh"]
    raw["payload"]["brief"] = brief
    for shot in raw["payload"]["script"]["shots"]:
        shot["voiceover"] = "测" * 80
    with pytest.raises(QAError, match="trim_copy"):
        run(raw, gateway=gateway, max_attempts=3)


def test_invalid_input_fails_fast(gateway) -> None:
    with pytest.raises(ValidationError):
        run({"project_id": "proj-n6", "payload": {}}, gateway=gateway)


def test_timeout(gateway) -> None:
    with pytest.raises(TimeoutError):
        run(_request(), gateway=gateway, timeout_s=0)


def test_timeout_after_slow_tts(gateway) -> None:
    original = gateway.tts

    def slow(text: str, **kwargs: Any) -> dict[str, Any]:
        time.sleep(0.2)
        return original(text, **kwargs)

    gateway.tts = slow
    with pytest.raises(TimeoutError):
        run(_request(), gateway=gateway, timeout_s=0.05)
