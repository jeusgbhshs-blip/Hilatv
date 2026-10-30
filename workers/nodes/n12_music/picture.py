"""Picture-cut error measured on a finished mp4.

Both clocks come from that file. Planned cut times are not an input: the
picture changes are frame steps, and the beats are onsets in the file's audio.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from workers.media.ffmpeg import RenderError, probe
from workers.nodes.n12_music.beats import detect_onsets, max_error_ms
from workers.nodes.n12_music.measure import read_wav

_WIDTH = 96
_HEIGHT = 54
# High-contrast cuts clear this easily. Low-contrast cuts sit just above it.
# A subtitle pop on a loud pattern stays under the relative part of the threshold.
_STEP_FLOOR = 6.0


@dataclass(frozen=True)
class FilmCuts:
    cuts_s: list[float]
    beats_s: list[float]
    error_ms: float
    step_peak: float
    step_median: float


def measure_picture_cuts(mp4: Path, work: Path) -> FilmCuts:
    """Max gap between a decoded picture change and an onset in the same file."""

    frames, fps = _frames(mp4)
    steps = _steps(frames)
    cuts = _cut_times(steps, fps)
    beats = _beats(mp4, work)
    if not cuts or not beats:
        error = 1_000_000.0
    else:
        error = max_error_ms(cuts, beats)
    ordered = sorted(steps)
    median = ordered[len(ordered) // 2] if ordered else 0.0
    return FilmCuts(
        cuts_s=cuts,
        beats_s=beats,
        error_ms=error,
        step_peak=max(steps) if steps else 0.0,
        step_median=median,
    )


def _frames(path: Path) -> tuple[list[bytes], float]:
    info = probe(path)
    fps = float(info["fps"])
    if fps <= 0:
        raise RenderError("the film has no frame rate")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-an",
            "-vf",
            f"scale={_WIDTH}:{_HEIGHT}:flags=neighbor,format=rgb24",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise RenderError(detail or "could not decode the film")
    size = _WIDTH * _HEIGHT * 3
    raw = proc.stdout
    if not raw or len(raw) % size != 0:
        raise RenderError("decoded frames are incomplete")
    frames = [raw[index : index + size] for index in range(0, len(raw), size)]
    return frames, fps


def _steps(frames: list[bytes]) -> list[float]:
    steps: list[float] = []
    for index in range(1, len(frames)):
        total = 0
        for left, right in zip(frames[index - 1], frames[index], strict=True):
            total += abs(left - right)
        steps.append(total / len(frames[index]))
    return steps


def _cut_times(steps: list[float], fps: float) -> list[float]:
    if not steps:
        return []
    peak = max(steps)
    median = sorted(steps)[len(steps) // 2]
    threshold = max(_STEP_FLOOR, median * 6, peak * 0.35)
    found: list[float] = []
    for index, value in enumerate(steps, start=1):
        if value < threshold:
            continue
        when = index / fps
        if found and when - found[-1] < 0.08:
            continue
        found.append(when)
    return found


def _beats(mp4: Path, work: Path) -> list[float]:
    """Onsets after a high pass, so the 440 Hz narration is not a beat."""

    dest = work / "film-audio.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-af",
            "highpass=f=3000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not dest.is_file():
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise RenderError(detail or "could not read the film audio")
    samples, rate = read_wav(dest)
    # AAC softens a ducked click. 1200 is still above the high-passed narration.
    return detect_onsets(samples, rate, jump=1200)
