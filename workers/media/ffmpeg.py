"""FFmpeg runner. Filter graphs for N15 live next to the timeline builder."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class RenderError(RuntimeError):
    """ffmpeg or ffprobe failed. The node may retry."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_ffmpeg(args: list[str]) -> None:
    if not ffmpeg_available():
        raise RenderError("ffmpeg and ffprobe are required")
    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-800:]
        raise RenderError(detail or "ffmpeg failed")


def probe(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RenderError("ffprobe is required")
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise RenderError(detail or "ffprobe failed")
    import json

    data = json.loads(proc.stdout.decode("utf-8"))
    video = next(item for item in data.get("streams", []) if item.get("codec_type") == "video")
    audio = [item for item in data.get("streams", []) if item.get("codec_type") == "audio"]
    return {
        "codec": video.get("codec_name"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": _rate(str(video.get("avg_frame_rate") or "0/1")),
        "duration_s": float(data.get("format", {}).get("duration") or 0),
        "audio_codecs": [item.get("codec_name") for item in audio],
    }


def playable(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderError("ffmpeg is required")
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-400:]
        raise RenderError(detail or "file is not playable")


def encode_plate(
    path: Path,
    *,
    rgb: tuple[int, int, int],
    width: int,
    height: int,
    frames: int,
    fps: int,
) -> None:
    """A flat-color shot. The plate has no glyphs; text is an overlay."""

    color = f"0x{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}:r={fps}",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-x264-params",
            "threads=1:sliced-threads=0:bframes=0",
            "-an",
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            str(path),
        ]
    )


def composite_overlay_png(background: Path, overlay: Path, xy: tuple[int, int], dest: Path) -> None:
    """RGB overlay used to prove text pixels survive the same filter the timeline uses."""

    x, y = xy
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(background),
            "-i",
            str(overlay),
            "-filter_complex",
            f"[0:v]format=rgba[bg];[bg][1:v]overlay={x}:{y}:format=rgb",
            "-frames:v",
            "1",
            str(dest),
        ]
    )


def _rate(value: str) -> float:
    if "/" not in value:
        return float(value or 0)
    num, den = value.split("/", 1)
    denom = float(den)
    if denom == 0:
        return 0.0
    return float(num) / denom
