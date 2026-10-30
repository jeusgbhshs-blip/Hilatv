"""Paint a 16:9 master whose subject is a red rectangle. Used by acceptance.

The rectangle is not text. drawbox treats ``t`` as thickness, so the mark is an
overlay whose ``t`` is the timestamp. Delivery checks that this red box stays
inside every output frame.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.media.ffmpeg import run_ffmpeg
from workers.nodes.n17_deliver.reframe import track_pixels
from workers.nodes.n17_deliver.schema import SubjectTrack


def encode_marked_master(
    path: Path,
    *,
    width: int,
    height: int,
    segments: list[tuple[float, float, SubjectTrack]],
    fps: int = 30,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    marks = path.parent / "marks"
    marks.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x203048:s={width}x{height}:r={fps}",
    ]
    chains: list[str] = []
    current = "0:v"
    total = 0.0
    for index, (start, duration, track) in enumerate(segments):
        total = max(total, start + duration)
        start_box, end_box = track_pixels(track, width, height)
        mark = marks / f"{index}.png"
        Image.new(
            "RGB",
            (max(2, int(start_box.w)), max(2, int(start_box.h))),
            (255, 0, 0),
        ).save(mark)
        span = max(duration, 0.001)
        end = start + duration
        x_expr = f"{start_box.x:.1f}+({end_box.x - start_box.x:.1f})*(t-{start:.3f})/{span:.3f}"
        y_expr = f"{start_box.y:.1f}+({end_box.y - start_box.y:.1f})*(t-{start:.3f})/{span:.3f}"
        args += ["-loop", "1", "-i", str(mark)]
        out = f"m{index}"
        chains.append(
            f"[{current}][{index + 1}:v]overlay=x='{x_expr}':y='{y_expr}':"
            f"enable='gte(t,{start:.3f})*lt(t,{end:.3f})'[{out}]"
        )
        current = out
    frames = max(1, int(round(max(total, 1 / fps) * fps)))
    if not chains:
        chains.append("[0:v]null[vout]")
        current = "vout"
    args += [
        "-filter_complex",
        ";".join(chains),
        "-map",
        f"[{current}]",
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-an",
        str(path),
    ]
    run_ffmpeg(args)
