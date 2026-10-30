"""Read and write the short clips N11 samples at 4 frames per second."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from workers.media.ffmpeg import run_ffmpeg

SAMPLE_FPS = 4


def write_mp4(frames: list[Image.Image], path: Path, *, fps: int = SAMPLE_FPS) -> None:
    if not frames:
        raise ValueError("video needs at least one frame")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for index, frame in enumerate(frames):
            frame.convert("RGB").save(folder / f"frame_{index:03d}.png")
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(fps),
                "-i",
                str(folder / "frame_%03d.png"),
                "-frames:v",
                str(len(frames)),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "8",
                str(path),
            ]
        )


def sample_frames(path: Path, *, fps: int = SAMPLE_FPS) -> list[Image.Image]:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vf",
                f"fps={fps}",
                str(folder / "out_%03d.png"),
            ]
        )
        files = sorted(folder.glob("out_*.png"))
        return [Image.open(item).convert("RGB") for item in files]
