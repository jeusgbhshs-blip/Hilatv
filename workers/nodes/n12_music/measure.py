"""Loudness meters. Numbers come from ffmpeg, not from the gain we applied."""

from __future__ import annotations

import array
import math
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


def ducking_db_on_mix(mix: Path, narration: Path, work: Path) -> float:
    """Music level under narration versus music in the gaps, recovered from the mix.

    The recovered stem is ``mix - narration``. Both windows are measured with
    ffmpeg ``volumedetect`` on that rendered stem. This is not a comparison of
    an unducked file against a copy multiplied by a fixed gain.
    """

    mix_pcm, rate = read_wav(mix)
    voice, voice_rate = read_wav(narration)
    if rate != voice_rate:
        raise RenderError("mix and narration sample rates differ")
    count = min(len(mix_pcm), len(voice))
    recovered = array.array("h", [0] * count)
    for index in range(count):
        recovered[index] = _clamp(int(mix_pcm[index]) - int(voice[index]))
    dest = work / "_recovered_music.wav"
    write_wav(dest, recovered, rate)
    spoken = speech_regions(voice[:count], rate)
    gaps = _gaps(count / rate, spoken)
    clicks = _jumps(recovered, rate)
    under = _clear_spans(spoken, clicks)
    open_spans = _clear_spans(gaps, clicks)
    if not under or not open_spans:
        raise RenderError("mix has no narration and gap spans clear of the clicks")
    quiet = _mean_db(dest, under)
    loud = _mean_db(dest, open_spans)
    return loud - quiet


def speech_regions(
    samples: array.array,
    sample_rate: int,
    *,
    threshold: int = 400,
) -> list[tuple[float, float]]:
    """Windows of energy, so a sine's zero crossings do not split the phrase."""

    hop = max(1, sample_rate // 100)
    window = max(hop, sample_rate // 50)
    hot_hops: list[bool] = []
    limit = max(0, len(samples) - window)
    for start in range(0, limit, hop):
        total = 0
        for sample in samples[start : start + window]:
            value = int(sample)
            total += value * value
        hot_hops.append(math.sqrt(total / window) >= threshold)
    regions: list[tuple[float, float]] = []
    begin: int | None = None
    for index, hot in enumerate(hot_hops):
        if hot and begin is None:
            begin = index
        elif not hot and begin is not None:
            regions.append((begin * hop / sample_rate, index * hop / sample_rate))
            begin = None
    if begin is not None:
        regions.append((begin * hop / sample_rate, len(hot_hops) * hop / sample_rate))
    return [(start, end) for start, end in regions if end - start >= 0.08]


def _gaps(duration_s: float, spoken: list[tuple[float, float]]) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in spoken:
        if start - cursor >= 0.12:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if duration_s - cursor >= 0.12:
        gaps.append((cursor, duration_s))
    return gaps


def _jumps(samples: array.array, sample_rate: int) -> list[float]:
    found: list[float] = []
    previous = 0
    refractory = int(0.08 * sample_rate)
    last = -refractory
    for index, sample in enumerate(samples):
        delta = abs(int(sample) - previous)
        previous = int(sample)
        if delta < 8000 or index - last < refractory:
            continue
        found.append(index / sample_rate)
        last = index
    return found


def _clear_spans(
    regions: list[tuple[float, float]],
    clicks: list[float],
    *,
    inset: float = 0.02,
    guard: float = 0.01,
) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for start, end in regions:
        inner_s = start + inset
        inner_e = end - inset
        if inner_e - inner_s < 0.04:
            continue
        cursor = inner_s
        for click in sorted(item for item in clicks if inner_s < item < inner_e):
            left = click - guard
            if left - cursor >= 0.04:
                spans.append((cursor, left))
            cursor = max(cursor, click + guard)
        if inner_e - cursor >= 0.04:
            spans.append((cursor, inner_e))
    return spans


def _mean_db(path: Path, spans: list[tuple[float, float]]) -> float:
    levels = [mean_volume_db(path, start, end) for start, end in spans]
    return sum(levels) / len(levels)


def _clamp(value: int) -> int:
    return max(-32768, min(32767, value))


def _run(args: list[str]) -> str:
    if not ffmpeg_available():
        raise RenderError("ffmpeg and ffprobe are required")
    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-500:]
        raise RenderError(detail or "ffmpeg failed")
    return proc.stderr.decode("utf-8", errors="replace")
