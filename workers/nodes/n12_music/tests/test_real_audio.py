"""Original offline audio fixtures must survive N6 -> N12 -> N15.

The fixtures are generated here (CC0 test signals), not customer recordings.
Fake TTS/ASR exercise the provider contract; they do not prove speech quality.
"""

from __future__ import annotations

import array
import copy
import math
from pathlib import Path
from typing import Any

import pytest

from gateway.media_bytes import prosody_timing, render_beat_pcm
from workers.media.audio import AudioError, audio_bytes, decode_audio, wav_bytes
from workers.nodes.n06_voiceover.node import run as voice_run
from workers.nodes.n12_music.accept import _fixture_brand, fixture
from workers.nodes.n12_music.measure import read_wav
from workers.nodes.n12_music.node import run as music_run
from workers.nodes.n12_music.qa import QAError
from workers.nodes.n15_compose.node import _audio
from workers.nodes.n15_compose.node import run as compose_run
from workers.nodes.n15_compose.qa import QAError as ComposeError
from workers.nodes.n15_compose.schema import N15Input

RATE = 48_000


def _signal(seconds: float, frequency: float) -> array.array:
    return array.array(
        "h",
        (
            round(5000 * math.sin(2 * math.pi * frequency * n / RATE))
            for n in range(round(seconds * RATE))
        ),
    )


class LocalAudioGateway:
    def __init__(self, root: Path, frequency: float = 330) -> None:
        self.root = root
        self.frequency = frequency
        self.music_calls = 0

    def tts(self, text: str, **kwargs: Any) -> dict:
        params = kwargs["params"]
        stamps, duration = prosody_timing(
            text, speed=params["speed"], pause_s=params["pause_s"], language=kwargs["language"]
        )
        path = self.root / f"{kwargs['shot_id']}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        frequency = self.frequency if kwargs["shot_id"] == "S01" else 770
        path.write_bytes(wav_bytes(_signal(duration, frequency)))
        return {
            "uri": path.as_uri(),
            "mock": False,
            "mime_type": "audio/wav",
            "duration_s": duration,
            "timestamps": stamps,
        }

    def asr(self, _uri: str, **kwargs: Any) -> dict:
        return {"mock": False, "text": kwargs["params"]["reference_text"]}

    def music(self, _prompt: str, **_kwargs: Any) -> dict:
        self.music_calls += 1
        return {
            "mock": True,
            "uri": "mock://music/test",
            "source": "hilatv-test-library/steady",
            "license": "CC0-1.0",
        }


def _voiced(root: Path, frequency: float = 330) -> tuple[dict, LocalAudioGateway]:
    gateway = LocalAudioGateway(root, frequency)
    result = voice_run(
        {"project_id": "real-audio", "payload": {"script": fixture()["script"]}},
        gateway=gateway,
        max_attempts=1,
    )
    assert all(take["provenance"] == "live" for take in result.payload["voiceovers"])
    assert all(take["heard_check"] == "verified" for take in result.payload["voiceovers"])
    return result.payload, gateway


def _mix(root: Path, voice: dict, gateway: LocalAudioGateway) -> dict:
    result = music_run(
        {"project_id": "real-audio", "payload": {**voice, "work_dir": str(root)}},
        gateway=gateway,
        max_attempts=1,
    )
    assert result.payload["audio_provenance"] == "mixed"
    assert result.payload["audio_track"]["provenance"] == "mixed"
    return result.payload


def _power(samples: array.array, frequency: float, start: float, end: float) -> float:
    segment = samples[round(start * RATE) : round(end * RATE)]
    cosine = sum(
        value * math.cos(2 * math.pi * frequency * n / RATE) for n, value in enumerate(segment)
    )
    sine = sum(
        value * math.sin(2 * math.pi * frequency * n / RATE) for n, value in enumerate(segment)
    )
    return cosine * cosine + sine * sine


def test_actual_takes_change_the_mix_and_keep_the_aligned_shot_clock(tmp_path: Path) -> None:
    voice, gateway = _voiced(tmp_path / "sources")
    first = _mix(tmp_path / "mix-a", voice, gateway)
    changed, gateway_b = _voiced(tmp_path / "changed", 990)
    second = _mix(tmp_path / "mix-b", changed, gateway_b)
    a, _rate = read_wav(Path(first["narration_path"]))
    b, _rate = read_wav(Path(second["narration_path"]))
    assert _power(a, 330, 0.1, 0.6) > 100 * _power(a, 990, 0.1, 0.6)
    assert _power(b, 990, 0.1, 0.6) > 100 * _power(b, 330, 0.1, 0.6)
    cuts = {cut["shot_id"]: cut for cut in first["cuts"]}
    third = cuts["S03"]["start_s"]
    assert _power(a, 770, third + 0.1, third + 0.6) > 100 * _power(a, 330, third + 0.1, third + 0.6)
    middle = cuts["S02"]
    assert not any(
        a[round((middle["start_s"] + 0.1) * RATE) : round((middle["end_s"] - 0.1) * RATE)]
    )


@pytest.mark.parametrize("fault", ["missing", "corrupt", "truncated", "outside", "wrong_duration"])
def test_bad_take_is_not_replaced_with_a_tone_or_billed_for_music(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    voice, gateway = _voiced(tmp_path / "sources")
    take = voice["voiceovers"][0]
    path = Path(take["uri"][7:])
    if fault == "missing":
        path.unlink()
    elif fault == "corrupt":
        path.write_bytes(b"not audio")
    elif fault == "truncated":
        path.write_bytes(path.read_bytes()[:-200])
    elif fault == "outside":
        monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "other-projects"))
    else:
        take["audio_s"] += 0.5
    with pytest.raises(QAError, match="unreadable|duration"):
        _mix(tmp_path / "mix", voice, gateway)
    assert gateway.music_calls == 0


def test_spoken_shot_without_a_take_fails_explicitly(tmp_path: Path) -> None:
    voice, gateway = _voiced(tmp_path / "sources")
    voice["voiceovers"] = []
    with pytest.raises(QAError, match="missing a voiceover asset"):
        _mix(tmp_path / "mix", voice, gateway)
    with pytest.raises(ComposeError, match="missing a voiceover asset"):
        _audio(N15Input.model_validate(voice), tmp_path / "edit", intro_s=0)


def test_compose_without_a_mix_uses_actual_take_bytes_and_packaging_offset(tmp_path: Path) -> None:
    voice, _gateway = _voiced(tmp_path / "sources")
    payload = N15Input.model_validate(voice)
    clips = _audio(payload, tmp_path / "edit", intro_s=1.2)
    pcm = decode_audio(Path(clips[0].path).read_bytes())
    assert _power(pcm, 330, 0.1, 0.6) > 100 * _power(pcm, 440, 0.1, 0.6)
    assert clips[0].start_s == 1.2
    assert clips[0].provenance == "live"
    third_start = 1.2 + sum(shot["duration_s"] for shot in voice["script"]["shots"][:2])
    assert abs(clips[1].start_s - third_start) < 0.001


def test_actual_mix_survives_encoded_n15_master_and_subtitle_mapping(tmp_path: Path) -> None:
    from workers.nodes.n13_subtitle.node import run as subtitles_run
    from workers.nodes.n14_packaging.node import run as packaging_run

    voice, gateway = _voiced(tmp_path / "sources")
    mixed = _mix(tmp_path / "mix", voice, gateway)
    original = copy.deepcopy(voice)
    subs = subtitles_run(
        {
            "project_id": "real-audio",
            "payload": {
                **voice,
                "width": 320,
                "height": 180,
                "work_dir": str(tmp_path / "subtitles"),
            },
        }
    )
    packaging = packaging_run(
        {
            "project_id": "real-audio",
            "payload": {
                "script": voice["script"],
                "brand_kit": _fixture_brand(tmp_path / "brand"),
                "intro": "fade",
                "width": 320,
                "height": 180,
                "work_dir": str(tmp_path / "packaging"),
            },
        }
    )
    body = {
        **voice,
        "aligned_script": mixed["aligned_script"],
        "audio_track": mixed["audio_track"],
        "licenses": mixed["segments"],
        "cues": subs.payload["cues"],
        "elements": packaging.payload["elements"],
        "intro_s": packaging.payload["intro_s"],
        "outro_s": packaging.payload["outro_s"],
        "width": 320,
        "height": 180,
        "work_dir": str(tmp_path / "edit"),
    }
    result = compose_run({"project_id": "real-audio", "payload": body}, max_attempts=1)
    assert result.payload["audio_provenance"] == "mixed"
    timeline = result.payload["timeline"]
    assert timeline["audio"][0]["path"] == mixed["mix_path"]
    master = decode_audio(Path(result.payload["exports"]["master"]).read_bytes())
    intro = packaging.payload["intro_s"]
    assert _power(master, 330, intro + 0.1, intro + 0.6) > 10 * _power(
        master, 440, intro + 0.1, intro + 0.6
    )
    third_start = intro + sum(shot["duration_s"] for shot in mixed["aligned_script"]["shots"][:2])
    assert _power(master, 770, third_start + 0.1, third_start + 0.6) > 10 * _power(
        master, 330, third_start + 0.1, third_start + 0.6
    )
    assert not any(master[round(0.1 * RATE) : round((intro - 0.1) * RATE)])
    old_start = sum(shot["duration_s"] for shot in voice["script"]["shots"][:2])
    third_cue = next(cue for cue in subs.payload["cues"] if cue["shot_id"] == "S03")
    rendered = next(
        overlay
        for overlay in timeline["overlays"]
        if overlay["kind"] == "subtitle" and overlay["text"] == third_cue["text"]
    )
    assert abs(rendered["start_s"] - (third_start + third_cue["start_s"] - old_start)) < 0.034
    assert voice == original


def test_reader_and_decoder_reject_empty_media(tmp_path: Path) -> None:
    with pytest.raises(AudioError):
        audio_bytes(str(tmp_path / "missing.wav"), allowed_roots=[tmp_path])
    with pytest.raises(AudioError):
        decode_audio(b"")


def test_real_music_bytes_are_used_instead_of_synthesized_replacement(tmp_path: Path) -> None:
    voice, gateway = _voiced(tmp_path / "sources")

    def real_music(_prompt: str, **kwargs: Any) -> dict:
        count = round(kwargs["duration_s"] * RATE)
        # A recognizable, original, authorized fixture layered over beat onsets.
        signal = _signal(kwargs["duration_s"], 1230)
        clicks = render_beat_pcm(n_samples=count, bpm=kwargs["params"]["bpm"], pad_amp=0, seed=0)
        music = array.array("h", (left + right for left, right in zip(signal, clicks, strict=True)))
        path = tmp_path / "licensed-music.wav"
        path.write_bytes(wav_bytes(music))
        return {
            "mock": False,
            "uri": path.as_uri(),
            "source": "authorized-fixture",
            "license": "CC0-1.0",
        }

    gateway.music = real_music
    mixed = _mix(tmp_path / "mix", voice, gateway)
    bed = decode_audio(Path(mixed["music_bed_path"]).read_bytes())
    assert _power(bed, 1230, 0.1, 0.6) > 100 * _power(bed, 220, 0.1, 0.6)


def test_mock_asr_does_not_claim_an_independent_hearing(tmp_path: Path) -> None:
    gateway = LocalAudioGateway(tmp_path / "sources")
    gateway.asr = lambda _uri, **kwargs: {"mock": True, "text": kwargs["params"]["reference_text"]}
    result = voice_run(
        {"project_id": "real-audio", "payload": {"script": fixture()["script"]}},
        gateway=gateway,
        max_attempts=1,
    )
    assert all(
        take["heard_check"] == "not_verified_in_mock" for take in result.payload["voiceovers"]
    )


def test_decoder_does_not_follow_playlist_references(tmp_path: Path) -> None:
    source = tmp_path / "outside.wav"
    source.write_bytes(wav_bytes(_signal(1, 330)))
    playlist = f"#EXTM3U\n#EXTINF:1,\n{source}\n".encode()
    with pytest.raises(AudioError, match="could not be decoded"):
        decode_audio(playlist)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_take",
        "duplicate_take",
        "missing_uri",
        "corrupt_uri",
        "missing_stem",
        "corrupt_stem",
        "music_only",
        "wrong_voice",
        "truncated_clock",
        "wrong_start",
    ],
)
def test_mix_cannot_bypass_missing_or_unconsumed_narration(tmp_path: Path, fault: str) -> None:
    voice, gateway = _voiced(tmp_path / "sources")
    mixed = _mix(tmp_path / "mix", voice, gateway)
    body = {
        **voice,
        "script": mixed["aligned_script"],
        "audio_track": mixed["audio_track"],
        "licenses": mixed["segments"],
    }
    if fault == "missing_take":
        body["voiceovers"] = []
    elif fault == "duplicate_take":
        body["voiceovers"].append(copy.deepcopy(body["voiceovers"][0]))
    elif fault == "missing_uri":
        Path(body["voiceovers"][0]["uri"][7:]).unlink()
    elif fault == "corrupt_uri":
        Path(body["voiceovers"][0]["uri"][7:]).write_bytes(b"corrupt")
    elif fault == "missing_stem":
        body["audio_track"]["narration_path"] = None
    elif fault == "corrupt_stem":
        Path(body["audio_track"]["narration_path"]).write_bytes(b"corrupt")
    elif fault in {"music_only", "wrong_voice"}:
        bed = decode_audio(Path(body["audio_track"]["music_path"]).read_bytes())
        sfx = decode_audio(Path(body["audio_track"]["sfx_path"]).read_bytes())
        narration = decode_audio(Path(body["audio_track"]["narration_path"]).read_bytes())
        if fault == "wrong_voice":
            narration = _signal(len(narration) / RATE, 1230)
            Path(body["audio_track"]["narration_path"]).write_bytes(wav_bytes(narration))
        replacement = array.array(
            "h",
            (
                max(-32768, min(32767, int(a) + int(b) + (int(c) if fault == "wrong_voice" else 0)))
                for a, b, c in zip(bed, sfx, narration, strict=True)
            ),
        )
        Path(body["audio_track"]["path"]).write_bytes(wav_bytes(replacement))
    elif fault == "truncated_clock":
        body["audio_track"]["duration_s"] = 0.5
    elif fault == "wrong_start":
        body["audio_track"]["start_s"] = 0.0
    with pytest.raises(ComposeError):
        _audio(N15Input.model_validate(body), tmp_path / "edit", intro_s=1.2)


def test_default_mock_mix_remains_mock_when_the_runtime_flag_later_becomes_live(
    tmp_path: Path, monkeypatch
) -> None:
    gateway = LocalAudioGateway(tmp_path / "unused-sources")
    voice = fixture()
    result = music_run(
        {"project_id": "mock-lineage", "payload": {**voice, "work_dir": str(tmp_path / "mix")}},
        gateway=gateway,
        max_attempts=1,
    )
    assert result.payload["audio_track"]["provenance"] == "mock"
    body = {
        **voice,
        "script": result.payload["aligned_script"],
        "audio_track": result.payload["audio_track"],
        "licenses": result.payload["segments"],
    }
    monkeypatch.setenv("HILATV_LIVE", "1")
    clips = _audio(N15Input.model_validate(body), tmp_path / "edit", intro_s=0)
    assert clips[0].provenance == "mock"


def test_mock_sfx_and_voice_provenance_cannot_be_retagged_live(tmp_path: Path) -> None:
    voice, gateway = _voiced(tmp_path / "sources")
    mixed = _mix(tmp_path / "mix", voice, gateway)
    body = {
        **voice,
        "script": mixed["aligned_script"],
        "audio_track": mixed["audio_track"],
        "licenses": mixed["segments"],
    }
    body["audio_track"]["provenance"] = "live"
    body["audio_track"]["source"] = "claimed-real-music"
    clips = _audio(N15Input.model_validate(body), tmp_path / "edit", intro_s=0)
    assert clips[0].provenance == "mixed"
