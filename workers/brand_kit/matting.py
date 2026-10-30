"""Local background removal and edge check.

The interface is what T13 should call. A later BiRefNet or RMBG adapter can
replace ``matte`` without changing callers. This build uses a flat-background
cutout so CI can run with no model weights and no API key.
"""

from __future__ import annotations

import io
import math

from PIL import Image

_LOW = 36.0
_HIGH = 96.0
_MAX_SIDE = 1024
_SAFE = 0.2


class ReplaceImageError(ValueError):
    """The cutout failed the edge check. The user should upload another picture."""

    retryable = False

    def __init__(self, message: str, *, target: str) -> None:
        super().__init__(message)
        self.target = target


class EdgeReport:
    """Alpha-edge QA from SPEC N2: jagged fringe or leftover background."""

    def __init__(self, *, jagged: bool, leftover_background: bool) -> None:
        self.jagged = jagged
        self.leftover_background = leftover_background
        self.ok = not jagged and not leftover_background
        notes: list[str] = []
        if jagged:
            notes.append("抠图边缘锯齿")
        if leftover_background:
            notes.append("残留背景")
        self.message = f"{'、'.join(notes)}。请更换图片" if notes else ""


class Cutout:
    def __init__(self, *, png: bytes, width: int, height: int, edge: EdgeReport) -> None:
        self.png = png
        self.width = width
        self.height = height
        self.edge = edge


def matte(image: bytes) -> Cutout:
    """Return a transparent PNG and an edge report. Does not raise on a bad edge."""

    source = _open(image)
    background = _border_color(source)
    cut = _remove(source, background)
    edge = _inspect(cut, background)
    return Cutout(png=_encode(cut), width=cut.width, height=cut.height, edge=edge)


def mono_plate(png: bytes, *, rgb: tuple[int, int, int]) -> bytes:
    """Recolor opaque pixels. Alpha stays, so the plate matches the cutout."""

    image = _open(png)
    out = Image.new("RGBA", image.size)
    src = image.load()
    dst = out.load()
    for y in range(image.height):
        for x in range(image.width):
            dst[x, y] = (*rgb, src[x, y][3])
    return _encode(out)


def with_safe_margin(png: bytes, *, ratio: float = _SAFE) -> tuple[bytes, float]:
    """Pad a transparent mark until the tightest margin is at least ``ratio``."""

    if not 0 < ratio < 0.5:
        raise ValueError("safe margin ratio must sit between 0 and 0.5")
    image = _open(png)
    current = _margin_ratio(image)
    if current is None:
        raise ReplaceImageError("抠图结果是空的。请更换图片", target="image")
    if current + 1e-6 >= ratio:
        return png, round(current, 4)
    longest = max(image.width, image.height)
    pad = math.ceil(ratio * longest / (1 - 2 * ratio))
    canvas = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(image, (pad, pad))
    padded = _margin_ratio(canvas)
    if padded is None or padded <= 0:
        raise ReplaceImageError("无法计算安全边距。请更换图片", target="image")
    return _encode(canvas), round(min(padded, 1.0), 4)


def _open(image: bytes) -> Image.Image:
    if not image:
        raise ReplaceImageError("图片是空的。请更换图片", target="image")
    try:
        loaded = Image.open(io.BytesIO(image))
        loaded.load()
    except Exception as exc:
        raise ReplaceImageError("图片无法读取。请更换图片", target="image") from exc
    rgba = loaded.convert("RGBA")
    if max(rgba.size) > _MAX_SIDE:
        rgba.thumbnail((_MAX_SIDE, _MAX_SIDE))
    return rgba


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _border_color(image: Image.Image) -> tuple[int, int, int]:
    pixels = image.load()
    samples: list[tuple[int, int, int]] = []
    for x in range(image.width):
        samples.append(pixels[x, 0][:3])
        samples.append(pixels[x, image.height - 1][:3])
    for y in range(image.height):
        samples.append(pixels[0, y][:3])
        samples.append(pixels[image.width - 1, y][:3])

    def median(channel: int) -> int:
        column = sorted(sample[channel] for sample in samples)
        return column[len(column) // 2]

    return (median(0), median(1), median(2))


def _distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def _remove(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    out = Image.new("RGBA", image.size)
    src = image.load()
    dst = out.load()
    span = _HIGH - _LOW
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = src[x, y]
            if alpha == 0:
                dst[x, y] = (red, green, blue, 0)
                continue
            distance = _distance((red, green, blue), background)
            if distance <= _LOW:
                opacity = 0
            elif distance >= _HIGH:
                opacity = 255
            else:
                opacity = int((distance - _LOW) * 255 / span)
            dst[x, y] = (red, green, blue, min(alpha, opacity))
    return out


def _inspect(image: Image.Image, background: tuple[int, int, int]) -> EdgeReport:
    pixels = image.load()
    border: list[tuple[int, int, int, int]] = []
    for x in range(image.width):
        border.append(pixels[x, 0])
        border.append(pixels[x, image.height - 1])
    for y in range(image.height):
        border.append(pixels[0, y])
        border.append(pixels[image.width - 1, y])
    opaque_background = 0
    for pixel in border:
        near = _distance(pixel[:3], background) <= _HIGH
        if pixel[3] > 200 and near:
            opaque_background += 1
    leftover = opaque_background / len(border) > 0.25
    flips: list[int] = []
    for y in range(image.height):
        changes = 0
        previous = pixels[0, y][3] > 128
        for x in range(1, image.width):
            current = pixels[x, y][3] > 128
            if current != previous:
                changes += 1
                previous = current
        if changes:
            flips.append(changes)
    jagged = bool(flips) and (sum(flips) / len(flips) > 4)
    return EdgeReport(jagged=jagged, leftover_background=leftover)


def _content_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    pixels = image.load()
    min_x, min_y = image.width, image.height
    max_x, max_y = -1, -1
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][3] > 16:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < 0:
        return None
    return min_x, min_y, max_x + 1, max_y + 1


def _margin_ratio(image: Image.Image) -> float | None:
    box = _content_box(image)
    if box is None or image.width == 0 or image.height == 0:
        return None
    left, top, right, bottom = box
    margins = (
        left / image.width,
        top / image.height,
        (image.width - right) / image.width,
        (image.height - bottom) / image.height,
    )
    return min(margins)
