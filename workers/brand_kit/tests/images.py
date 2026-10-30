"""Synthetic drawings. These are not customer photographs."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def logo_png() -> bytes:
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 48, 48), radius=6, fill=(10, 61, 145))
    return _png(image)


def product_png() -> bytes:
    image = Image.new("RGB", (80, 64), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.ellipse((22, 14, 58, 50), fill=(40, 90, 120))
    draw.rectangle((36, 28, 44, 52), fill=(180, 140, 60))
    return _png(image)


def noise_png() -> bytes:
    image = Image.new("RGB", (40, 40), (255, 255, 255))
    pixels = image.load()
    for y in range(40):
        for x in range(40):
            if (x + y) % 2 == 0:
                pixels[x, y] = (12, 12, 12)
            else:
                pixels[x, y] = (250, 250, 250)
    return _png(image)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
