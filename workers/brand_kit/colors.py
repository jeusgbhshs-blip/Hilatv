"""Pick primary, secondary, and accent from opaque logo pixels."""

from __future__ import annotations

import colorsys

from workers.brand_kit.matting import _open
from workers.schemas.brand import BrandColors


def extract_colors(png: bytes) -> BrandColors:
    image = _open(png)
    pixels = image.load()
    buckets: dict[tuple[int, int, int], int] = {}
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 128:
                continue
            key = (red // 16 * 16, green // 16 * 16, blue // 16 * 16)
            buckets[key] = buckets.get(key, 0) + 1
    if not buckets:
        primary = (15, 61, 110)
    else:
        ranked = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
        saturated = [color for color, _count in ranked if _saturation(color) >= 0.18]
        primary = saturated[0] if saturated else ranked[0][0]
    secondary = _mix(primary, (255, 255, 255), 0.72)
    accent = _accent(primary)
    return BrandColors(primary=_hex(primary), secondary=_hex(secondary), accent=_hex(accent))


def _saturation(color: tuple[int, int, int]) -> float:
    peak = max(color)
    if peak == 0:
        return 0.0
    return (peak - min(color)) / peak


def _mix(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    weight: float,
) -> tuple[int, int, int]:
    return tuple(int(left[index] * (1 - weight) + right[index] * weight) for index in range(3))


def _accent(color: tuple[int, int, int]) -> tuple[int, int, int]:
    hue, sat, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in color))
    if sat < 0.08:
        hue, sat = 0.58, 0.55
    else:
        hue = (hue + 0.13) % 1
        sat = min(1.0, max(0.35, sat))
    value = min(1.0, max(0.4, value))
    red, green, blue = colorsys.hsv_to_rgb(hue, sat, value)
    return (int(red * 255), int(green * 255), int(blue * 255))


def _hex(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
