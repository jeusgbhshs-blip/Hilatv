"""Loudness meters. Numbers come from ffmpeg, not from the gain we applied."""

from __future__ import annotations

import array
import re
import subprocess
import wave
from pathlib import Path

from gateway.media_bytes import MUSIC_RATE
from workers.media.ffmpeg import RenderError, ffmpeg_available

_INTEGRATED = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
_MEAN = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def write_wav(path: Path, samples: array.array, sample_rate: int = MUSIC_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


def read_wav(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        if handle.getsampwidth() != 2 or handle.getnchannels() < 1:
            raise RenderError(f"{path} is not 16-bit wav")
        raw = handle.readframes(handle.getnframes())
        samples = array.array("h")
        samples.frombytes(raw)
        if handle.getnchannels() > 1:
            samples = samples[:: handle.getnchannels()]
    return samples, rate


def integrated_lufs(path: Path) -> float:
    text = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "ebur128",
            "-f",
            "null",
            "-",
        ]
    )
    summary = text.split("Integrated loudness:")[-1]
    match = _INTEGRATED.search(summary)
    if match is None:
        raise RenderError("ebur128 did not report integrated loudness")
    return float(match.group(1))


def mean_volume_db(path: Path, start_s: float, end_s: float) -> float:
    if end_s - start_s < 0.03:
        raise RenderError("volume window is shorter than 30ms")
    text = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            f"atrim=start={start_s:.4f}:end={end_s:.4f},asetpts=PTS-STARTPTS,volumedetect",
            "-f",
            "null",
            "-",
        ]
    )
    match = _MEAN.search(text)
    if match is None:
        raise RenderError("volumedetect did not report mean volume")
    return float(match.group(1))


def _run(args: list[str]) -> str:
    if not ffmpeg_available():
        raise RenderError("ffmpeg and ffprobe are required")
    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-500:]
        raise RenderError(detail or "ffmpeg failed")
    return proc.stderr.decode("utf-8", errors="replace")
