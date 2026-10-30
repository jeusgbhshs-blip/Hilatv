"""Read the visible AI label from a decoded video frame.

The check uses Tesseract on pixels ffmpeg has already decoded. It does not
compare the overlay string the renderer stored.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from workers.media.ffmpeg import run_ffmpeg
from workers.schemas.label_lock import LABEL_TEXT


class OcrError(RuntimeError):
    pass


def decode_frame_index(video: Path, dest: Path, *, index: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"select=eq(n\\,{max(0, index)})",
            "-frames:v",
            "1",
            str(dest),
        ]
    )
    if not dest.is_file():
        raise OcrError(f"decoded no frame {index} from {video.name}")
    return dest


def decode_frame(video: Path, dest: Path, *, at_s: float = 0.2) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, at_s):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(dest),
        ]
    )
    if not dest.is_file():
        raise OcrError(f"decoded no frame from {video.name}")
    return dest


def recognize(image: Image.Image, *, psm: str = "6") -> str:
    """OCR one RGB image. The image is scaled so small burned glyphs stay legible."""

    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise OcrError("tesseract is required")
    scaled = image.convert("RGB").resize(
        (max(1, image.width * 3), max(1, image.height * 3)),
        Image.Resampling.NEAREST,
    )
    with tempfile.TemporaryDirectory(prefix="hilatv-ocr-") as folder:
        path = Path(folder) / "frame.png"
        scaled.save(path)
        proc = subprocess.run(
            [tesseract, str(path), "stdout", "-l", "chi_sim+eng", "--psm", psm],
            capture_output=True,
            check=False,
        )
    text = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0 and not text.strip():
        detail = proc.stderr.decode("utf-8", errors="replace")[-300:]
        raise OcrError(detail or "tesseract failed")
    return text


def label_visible(text: str) -> bool:
    folded = "".join(text.split())
    folded = folded.replace("Ａ", "A").replace("Ｉ", "I").replace("ｌ", "l")
    # Tesseract often reads the capital I in 「AI」 as l or 1.
    folded = folded.replace("Al生成", "AI生成").replace("A1生成", "AI生成")
    folded = folded.replace("AL生成", "AI生成")
    if LABEL_TEXT in folded or LABEL_TEXT in folded.upper():
        return True
    upper = folded.upper()
    return "AI" in upper and "生成" in folded


def read_label(
    video: Path,
    *,
    box: tuple[int, int, int, int] | None = None,
    at_s: float = 0.2,
) -> str:
    """Decode one frame and OCR it. ``box`` is x, y, w, h on that frame."""

    with tempfile.TemporaryDirectory(prefix="hilatv-frame-") as folder:
        frame_path = decode_frame(video, Path(folder) / "frame.png", at_s=at_s)
        image = Image.open(frame_path).convert("RGB")
        whole = recognize(image)
        if label_visible(whole):
            return whole
        if box is None:
            return whole
        x, y, w, h = box
        pad = 4
        crop = image.crop(
            (
                max(0, x - pad),
                max(0, y - pad),
                min(image.width, x + w + pad),
                min(image.height, y + h + pad),
            )
        )
        if crop.width < 2 or crop.height < 2:
            return whole
        for psm in ("8", "13", "7", "6"):
            text = recognize(crop, psm=psm)
            if label_visible(text):
                return text
        return whole
