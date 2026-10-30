"""Measure character sheets. The node does not draw a substitute face."""

from __future__ import annotations

from PIL import Image, ImageDraw

from workers.qa.pixels import cosine
from workers.qa.rules import face_embedding
from workers.qa.settings import face_min_similarity
from workers.schemas.brand import BrandColors


def min_view_cosine(views: dict[str, Image.Image]) -> float:
    vectors = {name: face_embedding(image) for name, image in views.items()}
    if any(item is None for item in vectors.values()):
        return 0.0
    pairs = (
        cosine(vectors["front"], vectors["side"]),
        cosine(vectors["front"], vectors["back"]),
        cosine(vectors["side"], vectors["back"]),
    )
    return min(pairs)


def views_pass(views: dict[str, Image.Image]) -> bool:
    return min_view_cosine(views) >= face_min_similarity()


def views_are_copies(views: dict[str, Image.Image]) -> bool:
    """True when a view repeats another bitmap, or is a horizontal mirror."""

    front = views["front"].convert("RGB")
    side = views["side"].convert("RGB")
    back = views["back"].convert("RGB")
    if len({front.tobytes(), side.tobytes(), back.tobytes()}) < 3:
        return True
    plates = (front, side, back)
    for left, right in ((front, side), (front, back), (side, back)):
        if (
            left.size == right.size
            and left.tobytes() == right.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
        ):
            return True
    del plates
    return False


def color_bars(colors: BrandColors, *, size: tuple[int, int] = (320, 180)) -> Image.Image:
    image = Image.new("RGB", size, _hex(colors.primary))
    draw = ImageDraw.Draw(image)
    width, height = size
    third = width // 3
    draw.rectangle((third, 0, third * 2, height), fill=_hex(colors.secondary))
    draw.rectangle((third * 2, 0, width, height), fill=_hex(colors.accent))
    return image


def _hex(value: str) -> tuple[int, int, int]:
    text = value.removeprefix("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
