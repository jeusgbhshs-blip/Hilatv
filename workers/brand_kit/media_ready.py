"""A generated picture counts only when its bytes can be read. mock:// does not."""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from workers.nodes.runtime import read_bytes


def ready_image_bytes(gateway: Any, uri: str) -> bytes | None:
    if not uri or uri.startswith("mock:"):
        return None
    loaded = read_bytes(gateway, uri)
    if loaded is None:
        return None
    data = loaded[1]
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None
    return data
