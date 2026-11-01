"""Rasterize overlay text with Noto Sans SC. The same call is the pixel reference."""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from workers.media.fonts import resolve_font


def hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"color must be #RRGGBB, got {value}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(resolve_font(weight)), size=max(8, int(size)))


def render_overlay(
    text: str,
    *,
    weight: str,
    font_size: int,
    fill: str,
    highlight: str = "#F5A623",
    spans: list[tuple[int, int]] | None = None,
    background: str | None = None,
    padding: int = 8,
    radius: int = 0,
    stroke: int = 0,
) -> Image.Image:
    """Draw ``text`` (newlines allowed). Spans are indexes into the full string."""

    font = load_font(weight, font_size)
    fill_rgba = (*hex_rgb(fill), 255)
    hi_rgba = (*hex_rgb(highlight), 255)
    stroke_rgba = (0, 0, 0, 255) if stroke else None
    lines = text.split("\n") if text else [""]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [probe.textlength(line, font=font) for line in lines]
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    gap = max(0, font_size // 5)
    text_w = int(math.ceil(max(widths) if widths else 0))
    text_h = line_h * len(lines) + gap * max(0, len(lines) - 1)
    pad = max(0, padding) + stroke
    width = max(1, text_w + pad * 2)
    height = max(1, text_h + pad * 2)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if background:
        draw.rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=radius,
            fill=(*hex_rgb(background), 255),
        )
    cursor = 0
    y = pad
    marks = spans or []
    for line in lines:
        _draw_line(
            draw,
            line,
            x=pad,
            y=y,
            font=font,
            fill=fill_rgba,
            highlight=hi_rgba,
            spans=_line_spans(marks, cursor, len(line)),
            stroke=stroke_rgba,
            stroke_width=stroke,
        )
        cursor += len(line) + 1
        y += line_h + gap
    return image


def fitting_text(
    spec: dict[str, Any], max_width: int, max_height: int
) -> tuple[Image.Image, dict[str, Any]]:
    """Rasterize at a legible font size that actually fits the safe rectangle."""

    fitted = dict(spec)
    size = int(fitted["font_size"])
    for candidate in range(size, 11, -1):
        fitted["font_size"] = candidate
        image = render_overlay(**fitted)
        if image.width <= max_width and image.height <= max_height:
            return image, fitted
    raise ValueError("overlay text does not fit the safe area at a readable font size")


def render_logo(
    source: bytes, *, max_width: int, max_height: int, safe_area_ratio: float = 0.2
) -> Image.Image:
    """Contain the supplied pixels, preserving color, alpha, and aspect ratio.

    Existing transparent padding is retained. More padding is added only when
    needed to meet the declared safe margin; a small source is never upscaled.
    """

    if not source or len(source) > 8 * 1024 * 1024:
        raise ValueError("logo source is empty or exceeds 8 MiB")
    if max_width < 1 or max_height < 1 or not 0 < safe_area_ratio < 0.5:
        raise ValueError("logo bounds or safe margin are invalid")
    try:
        with Image.open(io.BytesIO(source)) as opened:
            if opened.format not in {"PNG", "JPEG", "WEBP"} or getattr(opened, "n_frames", 1) != 1:
                raise ValueError("logo must be a still PNG, JPEG, or WebP")
            if opened.width * opened.height > 4_000_000 or max(opened.size) > 4096:
                raise ValueError("logo image dimensions are too large")
            opened.load()
            image = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("logo source could not be decoded") from exc
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("logo source is fully transparent")
    left, top, right, bottom = bounds
    ratio = safe_area_ratio
    pad_x = max(
        0, math.ceil((ratio * image.width - min(left, image.width - right)) / (1 - 2 * ratio))
    )
    pad_y = max(
        0, math.ceil((ratio * image.height - min(top, image.height - bottom)) / (1 - 2 * ratio))
    )
    canvas_width, canvas_height = image.width + 2 * pad_x, image.height + 2 * pad_y
    scale = min(1.0, max_width / canvas_width, max_height / canvas_height)
    if scale < 1:
        size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    if pad_x or pad_y:
        canvas = Image.new(
            "RGBA", (max(1, int(canvas_width * scale)), max(1, int(canvas_height * scale)))
        )
        canvas.paste(image, (int(pad_x * scale), int(pad_y * scale)))
        image = canvas
    return image


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def same_pixels(left: Image.Image, right: Image.Image) -> bool:
    return left.size == right.size and left.tobytes() == right.tobytes()


def _line_spans(marks: list[tuple[int, int]], cursor: int, length: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for start, end in marks:
        if end > cursor and start < cursor + length:
            spans.append((start - cursor, end - cursor))
    return spans


def _draw_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    *,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    highlight: tuple[int, int, int, int],
    spans: list[tuple[int, int]],
    stroke: tuple[int, int, int, int] | None,
    stroke_width: int,
) -> None:
    kwargs: dict[str, object] = {}
    if stroke and stroke_width:
        kwargs["stroke_width"] = stroke_width
        kwargs["stroke_fill"] = stroke
    draw.text((x, y), line, font=font, fill=fill, **kwargs)
    for start, end in spans:
        start = max(0, start)
        end = min(len(line), end)
        if end <= start:
            continue
        prefix = line[:start]
        offset = draw.textlength(prefix, font=font)
        draw.text((x + offset, y), line[start:end], font=font, fill=highlight, **kwargs)
