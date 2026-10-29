"""Trim a generated clip down to the shot length and keep transition handles.

N10 asks the video model for 5 or 10 seconds, then cuts a window of ``duration_s``
that starts after a head margin and ends before a tail margin.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MARGIN_S = 0.2


class TrimError(RuntimeError):
    """The clip could not be measured or cut."""


def margin_s() -> float:
    raw = os.getenv("HILATV_TRIM_MARGIN_S", "").strip()
    if not raw:
        return DEFAULT_MARGIN_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MARGIN_S
    if value <= 0 or value > 1:
        return DEFAULT_MARGIN_S
    return value


def best_generation_s(duration_s: float, *, margin: float | None = None) -> int:
    """Model-friendly length. The two supported intervals are 5 and 10 seconds."""

    pad = DEFAULT_MARGIN_S if margin is None else margin
    if duration_s + (2 * pad) <= 5:
        return 5
    return 10


def plan_trim(
    duration_s: float,
    source_s: float,
    *,
    margin: float | None = None,
) -> dict[str, float]:
    """Window of ``duration_s`` inside ``source_s``, with both ends left unused."""

    pad = DEFAULT_MARGIN_S if margin is None else margin
    if duration_s <= 0 or source_s <= 0:
        raise TrimError("durations must be positive")
    spare = source_s - duration_s
    if spare <= 0:
        raise TrimError("generated clip is not longer than the shot")
    head = pad if spare + 1e-6 >= pad * 2 else spare / 2
    if head <= 0:
        raise TrimError("no transition margin")
    end = head + duration_s
    tail = source_s - end
    if tail <= 0:
        raise TrimError("no tail margin")
    return {
        "trim_start_s": round(head, 3),
        "trim_end_s": round(end, 3),
        "head_margin_s": round(head, 3),
        "tail_margin_s": round(tail, 3),
        "output_duration_s": round(duration_s, 3),
        "source_duration_s": round(source_s, 3),
    }


def probe_duration_s(data: bytes) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise TrimError("ffprobe is required to measure the clip")
    with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
        handle.write(data)
        handle.flush()
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                handle.name,
            ],
            capture_output=True,
            check=False,
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-300:]
        raise TrimError(f"ffprobe failed: {detail}")
    try:
        duration = float(proc.stdout.decode().strip())
    except ValueError as exc:
        raise TrimError("ffprobe returned no duration") from exc
    if duration <= 0:
        raise TrimError("clip duration is empty")
    return duration


def trim_mp4(data: bytes, *, start_s: float, duration_s: float) -> bytes:
    """Re-encode the window. The color source has no burned-in text to preserve."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise TrimError("ffmpeg is required to trim the clip")
    with tempfile.TemporaryDirectory(prefix="hilatv-trim-") as tmp:
        src = Path(tmp) / "source.mp4"
        dst = Path(tmp) / "trimmed.mp4"
        src.write_bytes(data)
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-ss",
                f"{start_s:.3f}",
                "-t",
                f"{duration_s:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-an",
                str(dst),
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
            detail = proc.stderr.decode("utf-8", errors="replace")[-300:]
            raise TrimError(f"ffmpeg trim failed: {detail}")
        return dst.read_bytes()
