"""Small image measurements used by the rule checker.

Product shape is a 32×32 occupancy grid of pixels that differ from the border.
That grid is the local stand-in for a DINOv2 embedding: the weights are not in
this repo, and nothing here calls a vision vendor.
"""

from __future__ import annotations

import base64
import binascii
import math
from pathlib import Path

from PIL import Image, UnidentifiedImageError

GRID = 32


class MediaLoad:
    """Why a uri did not become pixels. ``ok`` is the only reviewable state."""

    def __init__(self, image: Image.Image | None, status: str, reason: str) -> None:
        self.image = image
        self.status = status
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.image is not None


def open_image(uri: str | None) -> Image.Image | None:
    """Pixels only. Callers that must tell missing from broken use ``load_image``."""

    loaded = load_image(uri)
    return loaded.image


def load_image(uri: str | None) -> MediaLoad:
    if uri is None or str(uri).strip() == "":
        return MediaLoad(None, "missing", "no media uri")
    text = str(uri).strip()
    if text.startswith("mock://"):
        return MediaLoad(None, "broken", f"mock uri is not reviewable: {text}")
    if text.startswith(("http://", "https://")):
        return MediaLoad(None, "broken", f"remote link was not fetched: {text}")
    if text.startswith("data:image"):
        raw = text.split(",", 1)[-1]
        try:
            payload = base64.b64decode(raw, validate=True)
        except binascii.Error:
            return MediaLoad(None, "unreadable", "data uri is not valid base64")
        return _decode(payload, "data uri")
    path = text[7:] if text.startswith("file://") else text
    file = Path(path)
    if not file.exists():
        return MediaLoad(None, "missing", f"file not found: {file}")
    if not file.is_file():
        return MediaLoad(None, "broken", f"path is not a file: {file}")
    try:
        payload = file.read_bytes()
    except OSError as exc:
        return MediaLoad(None, "unreadable", f"cannot read {file}: {exc}")
    return _decode(payload, str(file))


def _decode(payload: bytes, label: str) -> MediaLoad:
    if not payload:
        return MediaLoad(None, "unreadable", f"{label} is empty")
    try:
        image = Image.open(_buffer(payload))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return MediaLoad(None, "unreadable", f"cannot decode {label}: {exc}")
    return MediaLoad(image.convert("RGB"), "ok", "")


def open_png_bytes(raw: bytes) -> Image.Image:
    return Image.open(_buffer(raw)).convert("RGB")


def _buffer(raw: bytes):
    import io

    return io.BytesIO(raw)


def pack(image: Image.Image) -> tuple[bytes, int, int]:
    rgb = image.convert("RGB")
    return rgb.tobytes(), rgb.width, rgb.height


def luma_at(buf: bytes, width: int, x: int, y: int) -> int:
    index = (y * width + x) * 3
    red, green, blue = buf[index], buf[index + 1], buf[index + 2]
    return (red * 3 + green * 4 + blue) // 8


def pixel(buf: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    index = (y * width + x) * 3
    return buf[index], buf[index + 1], buf[index + 2]


def border_color(buf: bytes, width: int, height: int) -> tuple[int, int, int]:
    samples: list[tuple[int, int, int]] = []
    for x in range(width):
        samples.append(pixel(buf, width, x, 0))
        if height > 1:
            samples.append(pixel(buf, width, x, height - 1))
    for y in range(height):
        samples.append(pixel(buf, width, 0, y))
        if width > 1:
            samples.append(pixel(buf, width, width - 1, y))
    return _median_color(samples)


def foreground_mask(buf: bytes, width: int, height: int, *, distance: int = 48) -> bytearray:
    red, green, blue = border_color(buf, width, height)
    mask = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            pr, pg, pb = pixel(buf, width, x, y)
            delta = abs(pr - red) + abs(pg - green) + abs(pb - blue)
            if delta > distance:
                mask[y * width + x] = 1
    return mask


def occupancy(mask: bytearray, width: int, height: int, n: int = GRID) -> list[float]:
    cells = [0.0] * (n * n)
    counts = [0] * (n * n)
    for y in range(height):
        gy = min(n - 1, y * n // height)
        row = y * width
        for x in range(width):
            gx = min(n - 1, x * n // width)
            index = gy * n + gx
            counts[index] += 1
            cells[index] += mask[row + x]
    return [cells[i] / counts[i] if counts[i] else 0.0 for i in range(n * n)]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 1.0 if left_norm == right_norm else 0.0
    return dot / math.sqrt(left_norm * right_norm)


def shape_similarity(image: Image.Image, anchor: Image.Image) -> float:
    left = occupancy(*_mask_of(image))
    right = occupancy(*_mask_of(anchor))
    return cosine(left, right)


def _mask_of(image: Image.Image) -> tuple[bytearray, int, int]:
    buf, width, height = pack(image)
    return foreground_mask(buf, width, height), width, height


def mask_area(mask: bytearray) -> int:
    return sum(mask)


def touches_border(mask: bytearray, width: int, height: int) -> bool:
    if width < 3 or height < 3:
        return False
    for x in range(width):
        if mask[x] or mask[(height - 1) * width + x]:
            return True
    for y in range(height):
        if mask[y * width] or mask[y * width + width - 1]:
            return True
    return False


def _median_color(samples: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not samples:
        return (0, 0, 0)

    def mid(index: int) -> int:
        column = sorted(sample[index] for sample in samples)
        return column[len(column) // 2]

    return mid(0), mid(1), mid(2)
