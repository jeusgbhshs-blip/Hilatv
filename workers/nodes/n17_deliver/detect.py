"""Find the marked subject in a rendered frame.

The acceptance plates paint the subject pure red. A desaturated fill cannot
pass the same test, so a clipped crop shows up as a short box on the frame edge.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageChops

from workers.media.ffmpeg import RenderError, probe
from workers.nodes.n17_deliver.reframe import Rect


def read_rgb(path: Path) -> tuple[int, int, list[bytes]]:
    info = probe(path)
    width = int(info["width"])
    height = int(info["height"])
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
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
        raise RenderError(detail or "could not read frames")
    stride = width * height * 3
    if stride <= 0 or len(proc.stdout) < stride:
        raise RenderError("decoded frame is empty")
    count = len(proc.stdout) // stride
    frames = [proc.stdout[index * stride : (index + 1) * stride] for index in range(count)]
    return width, height, frames


def subject_bbox(frame: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    image = Image.frombytes("RGB", (width, height), frame)
    red, green, blue = image.split()
    dominant = ImageChops.subtract(red, ImageChops.lighter(green, blue))
    mask = dominant.point(lambda value: 255 if value >= 80 else 0)
    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    if right - left < 4 or bottom - top < 4:
        return None
    return left, top, right - left, bottom - top


def boxes_match(detected: tuple[int, int, int, int] | None, expected: Rect) -> bool:
    if detected is None:
        return False
    x, y, w, h = detected
    tolerance = max(10.0, 0.18 * max(expected.w, expected.h))
    center_x = x + w / 2
    center_y = y + h / 2
    expected_x = expected.x + expected.w / 2
    expected_y = expected.y + expected.h / 2
    if abs(center_x - expected_x) > tolerance or abs(center_y - expected_y) > tolerance:
        return False
    if w < expected.w * 0.72 or h < expected.h * 0.72:
        return False
    if w > expected.w * 1.35 or h > expected.h * 1.35:
        return False
    return True
