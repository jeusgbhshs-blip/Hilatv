"""Programmatic camera moves and motion graphics. Text is not drawn here."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from workers.qa.frames import write_mp4

CLIP_FPS = 12
_BORDER = (24, 52, 96)
_DISC = (70, 130, 190)


def frame_count(duration_s: float) -> int:
    """Enough frames to show a move, capped so a long shot stays cheap to encode."""

    return max(8, min(36, int(round(max(float(duration_s), 0.3) * CLIP_FPS))))


def ken_burns(
    image: Image.Image,
    dest: Path,
    *,
    size: tuple[int, int],
    frames: int,
) -> None:
    """Slow centered zoom. The crop stays inside the frame, so the edges are not bars."""

    write_mp4(_zoom(image, size, frames), dest, fps=CLIP_FPS)


def parallax(
    image: Image.Image,
    cutout: Image.Image,
    dest: Path,
    *,
    size: tuple[int, int],
    frames: int,
) -> None:
    """Background drifts farther than the cutout. Both stay inside the frame."""

    width, height = size
    background = image.convert("RGB").resize(
        (max(width + 8, int(width * 1.12)), max(height + 8, int(height * 1.12))),
        Image.Resampling.BILINEAR,
    )
    foreground = _fit_cutout(cutout, width, height)
    built: list[Image.Image] = []
    span = max(1, frames - 1)
    for index in range(frames):
        t = index / span
        left = int((background.width - width) * t * 0.8)
        top = (background.height - height) // 2
        frame = background.crop((left, top, left + width, top + height)).convert("RGBA")
        fx = int((width - foreground.width) / 2 + (t - 0.5) * width * 0.03)
        fy = int((height - foreground.height) / 2)
        frame.alpha_composite(foreground, (fx, fy))
        built.append(frame.convert("RGB"))
    write_mp4(built, dest, fps=CLIP_FPS)


def motion_graphic(
    dest: Path,
    *,
    size: tuple[int, int],
    frames: int,
    cutout: Image.Image | None,
    rgb: tuple[int, int, int] = _BORDER,
) -> str:
    """Moving background plus an optional product cutout. Returns the subject label."""

    width, height = size
    border = _safe_rgb(rgb)
    disc = _disc_rgb(border)
    foreground = _fit_cutout(cutout, width, height) if cutout is not None else None
    radius = int(min(width, height) * 0.26)
    built: list[Image.Image] = []
    span = max(1, frames - 1)
    for index in range(frames):
        t = index / span
        image = Image.new("RGB", size, border)
        draw = ImageDraw.Draw(image)
        cy = int(height * (0.56 - 0.06 * t))
        cx = width // 2
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=disc,
        )
        if foreground is not None:
            layer = image.convert("RGBA")
            fx = int((width - foreground.width) / 2)
            fy = int(height * (0.62 - 0.1 * t) - foreground.height / 2)
            fy = max(6, min(height - foreground.height - 6, fy))
            layer.alpha_composite(foreground, (fx, fy))
            image = layer.convert("RGB")
        built.append(image)
    write_mp4(built, dest, fps=CLIP_FPS)
    return "cutout" if foreground is not None else "generated_shape"


def _zoom(image: Image.Image, size: tuple[int, int], frames: int) -> list[Image.Image]:
    width, height = size
    base = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    built: list[Image.Image] = []
    span = max(1, frames - 1)
    for index in range(frames):
        zoom = 1.0 + 0.06 * index / span
        crop_w = max(2, int(round(width / zoom)))
        crop_h = max(2, int(round(height / zoom)))
        if crop_w % 2:
            crop_w -= 1
        if crop_h % 2:
            crop_h -= 1
        left = max(0, (width - crop_w) // 2)
        top = max(0, (height - crop_h) // 2)
        crop = base.crop((left, top, left + crop_w, top + crop_h))
        built.append(crop.resize(size, Image.Resampling.BILINEAR))
    return built


def _fit_cutout(cutout: Image.Image, width: int, height: int) -> Image.Image:
    foreground = cutout.convert("RGBA")
    limit = (max(8, int(width * 0.42)), max(8, int(height * 0.42)))
    foreground.thumbnail(limit, Image.Resampling.LANCZOS)
    return foreground


def _safe_rgb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = (int(channel) % 256 for channel in rgb)
    if red > green + 18 and red > blue + 28:
        return _BORDER
    return red, green, blue


def _disc_rgb(border: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = border
    shifted = (min(255, red + 46), min(255, green + 70), min(255, blue + 90))
    if abs(shifted[0] - red) + abs(shifted[1] - green) + abs(shifted[2] - blue) < 60:
        return _DISC
    return shifted
