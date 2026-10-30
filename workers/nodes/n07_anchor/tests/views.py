"""Fixture front, side, and back plates. Not used by the node.

These are different drawings. The side is a profile, the back is hair and a
neck, and none of them is a mirror of another. Tests and the accept script
hand them to a mock gateway. The node only measures what that gateway returns.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def _skin(y: int, span: int, shade: float) -> tuple[int, int, int]:
    t = y / max(span, 1)
    red = int(230 - 40 * t - 15 * shade)
    green = int(176 - 36 * t - 10 * shade)
    blue = int(146 - 30 * t - 8 * shade)
    return (max(0, red), max(0, green), max(0, blue))


def front_view() -> Image.Image:
    image = Image.new("RGB", (220, 260), (28, 40, 62))
    pixels = image.load()
    draw = ImageDraw.Draw(image)
    draw.polygon([(40, 200), (180, 200), (210, 259), (10, 259)], fill=(50, 70, 110))
    for y in range(30, 190):
        for x in range(50, 170):
            nx = (x - 110) / 60
            ny = (y - 100) / 75
            if nx * nx + ny * ny <= 1:
                pixels[x, y] = _skin(y - 30, 160, abs(nx) * 0.3)
    draw.ellipse((78, 88, 96, 108), fill=(20, 16, 16))
    draw.ellipse((124, 88, 142, 108), fill=(20, 16, 16))
    draw.polygon([(104, 108), (116, 108), (110, 128)], fill=(186, 132, 112))
    return image


def side_view() -> Image.Image:
    image = Image.new("RGB", (220, 260), (22, 34, 48))
    pixels = image.load()
    draw = ImageDraw.Draw(image)
    draw.polygon([(90, 210), (160, 200), (190, 259), (70, 259)], fill=(40, 55, 80))
    for y in range(36, 188):
        for x in range(70, 150):
            nx = (x - 100) / 42
            ny = (y - 104) / 72
            if nx * nx + ny * ny <= 1:
                pixels[x, y] = _skin(y - 36, 152, max(0.0, nx) * 0.8)
    draw.polygon([(70, 118), (100, 102), (100, 132)], fill=(214, 160, 130))
    draw.ellipse((108, 90, 124, 106), fill=(20, 16, 16))
    draw.ellipse((138, 96, 158, 128), fill=(200, 150, 124))
    return image


def back_view() -> Image.Image:
    image = Image.new("RGB", (220, 260), (18, 28, 40))
    pixels = image.load()
    draw = ImageDraw.Draw(image)
    draw.polygon([(50, 200), (170, 200), (200, 259), (20, 259)], fill=(36, 48, 70))
    draw.ellipse((55, 28, 165, 170), fill=(42, 32, 28))
    draw.ellipse((40, 90, 62, 130), fill=(206, 156, 128))
    draw.ellipse((158, 90, 180, 130), fill=(206, 156, 128))
    for y in range(150, 210):
        for x in range(90, 130):
            pixels[x, y] = _skin(y - 150, 60, abs(x - 110) / 40)
    return image


def expression_sheet() -> Image.Image:
    """A quiet plate. The node stores the gateway's sheet; it does not draw one."""

    return Image.new("RGB", (220, 260), (32, 44, 58))


def view_image(name: str) -> Image.Image:
    return {
        "front": front_view,
        "side": side_view,
        "back": back_view,
        "expressions": expression_sheet,
    }[name]()


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
