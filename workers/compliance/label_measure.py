"""Explicit AI label geometry. GB 45438-2025 §5.4.

The mark is text at a corner, on screen from the first frame, with a measured
glyph box at least 5% of the frame's short side, and it stays up for at least
two seconds. Glyph height is the ink bounding box, not the font's em size.

Films shorter than ``HILATV_AI_LABEL_MIN_S`` (default 2) are refused.
待 song 确认 whether a shorter cut may ship.
"""

from __future__ import annotations

import math
import os

from PIL import Image

from workers.media.raster import load_font


def label_min_seconds() -> float:
    raw = os.getenv("HILATV_AI_LABEL_MIN_S", "2").strip() or "2"
    try:
        value = float(raw)
    except ValueError:
        return 2.0
    if value <= 0:
        return 2.0
    return value


def minimum_glyph_px(short_side: int) -> int:
    """Smallest ink height that is still 5% of the short side."""

    return max(1, math.ceil(short_side * 0.05 - 1e-9))


def glyph_ink_height(image: Image.Image) -> int:
    """Height of the light glyphs inside a rendered or decoded label."""

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    rows: list[int] = []
    for y in range(height):
        if any(_ink(pixels[x, y]) for x in range(width)):
            rows.append(y)
    if not rows:
        return 0
    return rows[-1] - rows[0] + 1


def font_ink_height(text: str, font_size: int) -> int:
    bbox = load_font("bold", font_size).getbbox(text)
    return max(0, bbox[3] - bbox[1])


def assert_label_duration(duration_s: float) -> None:
    minimum = label_min_seconds()
    if duration_s + 1e-3 < minimum:
        raise ValueError(
            f"成片 {duration_s:.3f}s 短于显式标识要求的 {minimum:g}s，拒绝导出"
            "（HILATV_AI_LABEL_MIN_S，待 song 确认）"
        )


def _ink(pixel: tuple[int, ...]) -> bool:
    return pixel[0] >= 180 and pixel[1] >= 180 and pixel[2] >= 180
