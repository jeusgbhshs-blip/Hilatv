"""Each ratio export keeps a caller-supplied soundtrack on the audio timeline."""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

from workers.media.ffmpeg import probe, run_ffmpeg
from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.sample import acceptance_request

_RATE = 48000
_TONE = 100.0


def test_three_ratios_carry_the_soundtrack(tmp_path: Path, gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    request = acceptance_request(tmp_path, project_id="track-t17", languages=["zh"])
    project = tmp_path / "track-t17"
    tone = project / "bed.wav"
    _tone(tone, seconds=2.0)
    request["payload"]["audio_track"] = str(tone)
    result = run(request, gateway=gateway)
    versions = [
        item
        for item in result.payload["versions"]
        if item["language"] == "zh" and item["aspect_ratio"] in {"16:9", "9:16", "1:1"}
    ]
    assert {item["aspect_ratio"] for item in versions} == {"16:9", "9:16", "1:1"}
    for item in versions:
        info = probe(Path(item["path"]))
        assert info["audio_codecs"]
        decoded = tmp_path / f"{item['aspect_ratio'].replace(':', '')}.wav"
        assert _tone_dominates(Path(item["path"]), decoded)


def _tone(path: Path, *, seconds: float) -> None:
    frames = int(_RATE * seconds)
    samples = array.array("h", [0] * frames)
    for index in range(frames):
        samples[index] = int(14000 * math.sin(2 * math.pi * _TONE * index / _RATE))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_RATE)
        handle.writeframes(samples.tobytes())


def _tone_dominates(mp4: Path, dest: Path) -> bool:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(mp4),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(_RATE),
            str(dest),
        ]
    )
    with wave.open(str(dest), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    samples = array.array("h")
    samples.frombytes(raw)
    low = _goertzel(samples, _RATE, _TONE)
    high = _goertzel(samples, _RATE, 2000.0)
    return low > high * 4 and low > 1_000_000


def _goertzel(samples: array.array, rate: int, freq: float) -> float:
    if not samples:
        return 0.0
    coeff = 2 * math.cos(2 * math.pi * freq / rate)
    first = 0.0
    second = 0.0
    for sample in samples:
        current = int(sample) + coeff * first - second
        second = first
        first = current
    power = first * first + second * second - coeff * first * second
    return power / len(samples)
