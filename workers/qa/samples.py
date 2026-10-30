"""Synthetic plates for the interception set.

Every bad frame is drawn here with Pillow. Nothing is a photograph, and nothing
is a real person's face. The shapes are:

- a flat workshop gray field and a centered steel block (the product)
- bitmap words, including a phone line, painted into the frame
- a dense patch of random strokes (garbled writing)
- the same block sheared, pinched, or bulged against an undistorted anchor
- an oval stand-in face with two eyes, or the same oval with three eyes
- solid black bars, a periodic corner hatch, a block cut by the frame,
  a tiny block, and a plate under the resolution floor
- 4 fps clips: two frames (0.5 s) of shear, or one flashed white frame

Clean plates use the undistorted block and, where a face is expected, two eyes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from workers.qa.frames import write_mp4

WIDTH = 320
HEIGHT = 180
BG = (58, 62, 66)
STEEL = (150, 176, 196)
INK = (12, 12, 14)
SKIN = (224, 176, 144)
_FONT_PATH = (
    Path(__file__).resolve().parents[2]
    / "templates"
    / "packaging"
    / "fonts"
    / "NotoSansSC-Regular.otf"
)


@dataclass(frozen=True)
class Sample:
    sample_id: str
    kind: str
    defect: str
    path: Path
    anchor: Path | None
    expected_faces: int


def build_catalog(directory: Path) -> list[Sample]:
    directory.mkdir(parents=True, exist_ok=True)
    anchor = _save(directory / "anchor.png", _plate("rect"))
    rows: list[Sample] = []
    rows.extend(_stills(directory, anchor))
    rows.extend(_clips(directory, anchor))
    return rows


def clean_plate() -> Image.Image:
    return _plate("rect")


def _stills(directory: Path, anchor: Path) -> list[Sample]:
    specs: list[tuple[str, str, Image.Image, int, bool]] = []
    phrases = (
        "SALE HOT LINE",
        "热线 400-800-1234",
        "EXTRA TEXT",
        "PRICE 199",
        "CALL NOW",
        "NO LOGO HERE",
    )
    for index, phrase in enumerate(phrases):
        plate = _plate("rect", text=phrase, text_y=12 + index * 4)
        specs.append((f"text-{index}", "extra_text", plate, 0, True))
    for index in range(6):
        specs.append((f"garbled-{index}", "garbled_text", _plate("rect", garbled=index), 0, True))
    for index, shape in enumerate(("shear", "bulge", "pinch", "shear", "bulge", "pinch")):
        specs.append((f"deform-{index}", "product_deform", _plate(shape, shift=index * 3), 0, True))
    for index in range(4):
        face = _face(eyes=3, shift=index * 4)
        specs.append((f"face-break-{index}", "face_collapse", face, 1, False))
    for index in range(2):
        specs.append((f"face-extra-{index}", "face_count", _face(eyes=2), 0, False))
    for index, side in enumerate(("top", "bottom", "left", "right")):
        specs.append((f"bar-{index}", "black_bar", _bars(_plate("rect"), side), 0, True))
    for index in range(4):
        marked = _watermark(_plate("rect"), phase=index)
        specs.append((f"mark-{index}", "watermark", marked, 0, True))
    for index in range(4):
        specs.append((f"tiny-{index}", "low_resolution", _plate("rect").resize((96, 54)), 0, False))
    specs.append(("clip-left", "bad_composition", _plate("clip_left"), 0, True))
    specs.append(("clip-right", "bad_composition", _plate("clip_right"), 0, True))
    specs.append(("tiny-subject", "bad_composition", _plate("tiny"), 0, True))
    for index in range(4):
        specs.append((f"clean-{index}", "clean", _plate("rect"), 0, True))
    specs.append(("clean-face", "clean", _face(eyes=2), 1, False))

    rows: list[Sample] = []
    for sample_id, defect, image, faces, use_anchor in specs:
        path = _save(directory / f"{sample_id}.png", image)
        rows.append(
            Sample(
                sample_id=sample_id,
                kind="image",
                defect=defect,
                path=path,
                anchor=anchor if use_anchor else None,
                expected_faces=faces,
            )
        )
    return rows


def _clips(directory: Path, anchor: Path) -> list[Sample]:
    rows: list[Sample] = []
    clean_frames = [_plate("rect") for _ in range(8)]
    for index, at in enumerate((2, 3, 4, 5)):
        frames = list(clean_frames)
        frames[at] = _plate("shear")
        frames[at + 1] = _plate("pinch")
        path = directory / f"clip-deform-{index}.mp4"
        write_mp4(frames, path, fps=4)
        rows.append(Sample(f"clip-deform-{index}", "video", "product_deform", path, anchor, 0))
    for index, at in enumerate((1, 3, 4, 6)):
        frames = list(clean_frames)
        frames[at] = Image.new("RGB", (WIDTH, HEIGHT), (240, 240, 240))
        path = directory / f"clip-flicker-{index}.mp4"
        write_mp4(frames, path, fps=4)
        rows.append(Sample(f"clip-flicker-{index}", "video", "flicker", path, anchor, 0))
    clean_path = directory / "clip-clean.mp4"
    write_mp4(clean_frames, clean_path, fps=4)
    rows.append(Sample("clip-clean", "video", "clean", clean_path, anchor, 0))
    return rows


def _plate(
    shape: str,
    *,
    text: str = "",
    text_y: int = 16,
    garbled: int | None = None,
    shift: int = 0,
) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    box = (90 + shift, 46, 230 + shift, 138)
    _product(draw, box, shape)
    if text:
        draw.text((24, text_y), text, fill=INK, font=_font(22))
    if garbled is not None:
        _scribble(draw, garbled)
    return image


def _product(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], shape: str) -> None:
    x0, y0, x1, y1 = box
    if shape == "rect":
        draw.rectangle(box, fill=STEEL)
        return
    if shape == "shear":
        draw.polygon([(x0 + 42, y0), (x1, y0), (x1 - 42, y1), (x0, y1)], fill=STEEL)
        return
    if shape == "bulge":
        draw.ellipse((x0 - 8, y0 + 16, x1 + 8, y1 - 8), fill=STEEL)
        return
    if shape == "pinch":
        mid_x = (x0 + x1) // 2
        mid_y = (y0 + y1) // 2
        draw.polygon(
            [(x0, y0), (x1, y0), (mid_x + 18, mid_y), (x1, y1), (x0, y1), (mid_x - 18, mid_y)],
            fill=STEEL,
        )
        return
    if shape == "clip_left":
        draw.rectangle((0, y0, 70, y1), fill=STEEL)
        return
    if shape == "clip_right":
        draw.rectangle((WIDTH - 70, y0, WIDTH - 1, y1), fill=STEEL)
        return
    if shape == "tiny":
        draw.rectangle((WIDTH - 36, 10, WIDTH - 18, 26), fill=STEEL)
        return
    raise ValueError(shape)


def _scribble(draw: ImageDraw.ImageDraw, seed: int) -> None:
    rng = random.Random(1000 + seed)
    x0, y0 = 18, 14 + (seed % 3) * 6
    for _ in range(70):
        x = x0 + rng.randint(0, 150)
        y = y0 + rng.randint(0, 36)
        draw.line((x, y, x + rng.randint(-18, 22), y + rng.randint(-6, 8)), fill=INK, width=2)


def _face(eyes: int, shift: int = 0) -> Image.Image:
    image = _plate("rect")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 118 + shift, 48, 196 + shift, 140
    draw.ellipse((left, top, right, bottom), fill=SKIN)
    eye_y = top + 28
    positions = [left + 22, left + 52]
    if eyes == 3:
        positions = [left + 16, left + 36, left + 56]
    for center in positions[:eyes]:
        draw.ellipse((center, eye_y, center + 10, eye_y + 10), fill=INK)
    draw.arc((left + 24, top + 58, right - 24, bottom - 16), 10, 170, fill=INK, width=2)
    return image


def _bars(image: Image.Image, side: str) -> Image.Image:
    frame = image.copy()
    draw = ImageDraw.Draw(frame)
    if side == "top":
        draw.rectangle((0, 0, WIDTH, 28), fill=(0, 0, 0))
    elif side == "bottom":
        draw.rectangle((0, HEIGHT - 28, WIDTH, HEIGHT), fill=(0, 0, 0))
    elif side == "left":
        draw.rectangle((0, 0, 28, HEIGHT), fill=(0, 0, 0))
    else:
        draw.rectangle((WIDTH - 28, 0, WIDTH, HEIGHT), fill=(0, 0, 0))
    return frame


def _watermark(image: Image.Image, *, phase: int) -> Image.Image:
    """Inset hatch so the mark is periodic and does not touch the frame edge."""

    frame = image.copy()
    draw = ImageDraw.Draw(frame)
    light = (130, 134, 138)
    origin_x = WIDTH - 50
    origin_y = HEIGHT - 28
    for offset in range(phase % 4, 36, 4):
        draw.line(
            (origin_x + offset, origin_y, origin_x + offset, origin_y + 20),
            fill=light,
            width=1,
        )
    return frame


def _font(size: int) -> ImageFont.ImageFont:
    if _FONT_PATH.is_file():
        return ImageFont.truetype(str(_FONT_PATH), size=size)
    return ImageFont.load_default()


def _save(path: Path, image: Image.Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path
