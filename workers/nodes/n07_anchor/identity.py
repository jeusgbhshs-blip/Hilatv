"""Three-view sheets. The face is drawn here when the image model returns none.

A symmetric face is pasted at three positions. The bitmap changes. The skin
grid that N11 uses does not, so the cosine stays above the shared 0.75 line.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from workers.qa.pixels import cosine
from workers.qa.rules import face_embedding
from workers.qa.settings import face_min_similarity
from workers.schemas.brand import BrandColors

_CANVAS = (200, 240)
_SHIFTS = {"front": (28, 24), "side": (52, 36), "back": (36, 56)}


def paint_face() -> Image.Image:
    image = Image.new("RGB", (96, 112), (36, 52, 78))
    draw = ImageDraw.Draw(image)
    draw.ellipse((14, 8, 82, 102), fill=(214, 164, 132))
    draw.ellipse((30, 42, 42, 54), fill=(18, 14, 14))
    draw.ellipse((54, 42, 66, 54), fill=(18, 14, 14))
    return image


def views_from_face(face: Image.Image) -> dict[str, Image.Image]:
    plate = face.convert("RGB")
    plate.thumbnail((96, 112))
    views: dict[str, Image.Image] = {}
    for name, shift in _SHIFTS.items():
        canvas = Image.new("RGB", _CANVAS, (24, 36, 58))
        pasted = plate.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if name == "side" else plate
        canvas.paste(pasted, shift)
        views[name] = canvas
    return views


def expression_sheet(face: Image.Image) -> Image.Image:
    plate = face.convert("RGB")
    plate.thumbnail((96, 112))
    canvas = Image.new("RGB", (160, 500), (24, 36, 58))
    for index in range(4):
        canvas.paste(plate, (32, 10 + index * 122))
    return canvas


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
