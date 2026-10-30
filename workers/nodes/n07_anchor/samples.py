"""Synthetic product art drawn in code. Not a customer photograph."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def marked_product() -> bytes:
    """A flat product with one solid mark. The mark is the packaging stand-in."""

    image = Image.new("RGB", (120, 100), (248, 248, 248))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 14, 104, 86), radius=10, fill=(18, 72, 150))
    draw.rectangle((46, 34, 74, 62), fill=(220, 40, 40))
    return _png(image)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
