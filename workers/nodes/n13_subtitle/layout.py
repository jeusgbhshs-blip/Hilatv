"""Place a subtitle block inside the platform safe area, above the product."""

from __future__ import annotations

from dataclasses import dataclass

from workers.media.packaging import Insets


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Placement:
    x_ratio: float
    y_ratio: float
    block_h: float
    moved: bool


def place_subtitle(
    *,
    safe: Insets,
    subject: Box | None,
    text_w_ratio: float,
    line_h_ratio: float,
) -> Placement:
    """Return the top-left of the block. A subject collision moves the block up."""

    block_h = line_h_ratio
    width = min(max(text_w_ratio, 0.0), max(0.0, 1 - safe.left - safe.right))
    y = 1 - safe.bottom - block_h
    x = safe.left
    if width > 0:
        centered = (1 - width) / 2
        x = min(max(centered, safe.left), max(safe.left, 1 - safe.right - width))
    y = min(max(y, safe.top), 1 - block_h)
    moved = False
    if subject is not None and _overlaps(x, y, width, block_h, subject):
        lifted = subject.y - 0.012 - block_h
        y = max(safe.top, lifted)
        moved = True
    return Placement(x_ratio=x, y_ratio=y, block_h=block_h, moved=moved)


def _overlaps(x: float, y: float, w: float, h: float, box: Box) -> bool:
    if w <= 0 or h <= 0 or box.w <= 0 or box.h <= 0:
        return False
    return not (x + w <= box.x or box.x + box.w <= x or y + h <= box.y or box.y + box.h <= y)
