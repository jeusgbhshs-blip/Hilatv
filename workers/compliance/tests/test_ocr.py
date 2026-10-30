"""OCR reads 「AI生成」 from a decoded frame, and ffprobe reads the AIGC tag."""

from __future__ import annotations

from pathlib import Path

from workers.compliance.metadata import metadata_args, new_produce_id, read_aigc
from workers.compliance.ocr import label_visible, read_label
from workers.media.ffmpeg import encode_plate, run_ffmpeg
from workers.media.raster import render_overlay, save_png


def test_decoded_frame_shows_the_label_and_ffprobe_reads_metadata(tmp_path: Path) -> None:
    plate = tmp_path / "plate.mp4"
    encode_plate(plate, rgb=(16, 16, 16), width=320, height=180, frames=15, fps=30)
    image = render_overlay(
        "AI生成",
        weight="bold",
        font_size=36,
        fill="#FFFFFF",
        background="#111111",
        padding=6,
        radius=4,
    )
    png = tmp_path / "label.png"
    save_png(image, png)
    dest = tmp_path / "labeled.mp4"
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(plate),
            "-i",
            str(png),
            "-filter_complex",
            "[0:v][1:v]overlay=8:8",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            *metadata_args(content_id="ocr-sample"),
            "-an",
            str(dest),
        ]
    )
    text = read_label(dest, box=(8, 8, image.width, image.height), at_s=0.1)
    assert label_visible(text), text
    meta = read_aigc(dest)
    assert meta["Label"] == "1"
    assert meta["ContentProducer"] == "PENDING-SONG-CONFIRM"
    assert meta["ProduceID"]
    assert meta["ReservedCode1"]
    assert new_produce_id() != new_produce_id()
