"""Explicit frame geometry shared by provider boundaries and deterministic previews."""

from __future__ import annotations

from math import gcd
from typing import Any

from gateway.errors import AdapterError

# Pixel-mode sizes meet Seedream 4.0's >=921600 pixel bound while retaining
# the requested ratio exactly. No natural-language shape inference is required.
IMAGE_SIZES = {
    "16:9": "1280x720",
    "9:16": "720x1280",
    "1:1": "1024x1024",
    "4:3": "1152x864",
    "3:4": "864x1152",
    "3:2": "1248x832",
    "2:3": "832x1248",
    "4:5": "896x1120",
    "21:9": "1512x648",
}
SEEDANCE_NATIVE_RATIOS = frozenset({"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"})


def ratio_parts(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or value not in IMAGE_SIZES:
        raise AdapterError("unsupported frame ratio")
    a, b = (int(part) for part in value.split(":"))
    factor = gcd(a, b)
    return a // factor, b // factor


def image_size_for_ratio(value: object) -> str:
    ratio_parts(value)
    return IMAGE_SIZES[str(value)]


def mock_dimensions(params: dict[str, Any]) -> tuple[int, int]:
    ratio = params.get("ratio")
    if ratio is None:
        return 320, 180
    a, b = ratio_parts(ratio)
    unit = max(2, int(320 / max(a, b) / 2) * 2)
    return a * unit, b * unit
