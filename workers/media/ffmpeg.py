"""FFmpeg availability check. Rendering stays a stub until T09."""

from __future__ import annotations

import shutil


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def render_not_ready() -> dict[str, str]:
    return {"status": "stub", "task": "T09"}
