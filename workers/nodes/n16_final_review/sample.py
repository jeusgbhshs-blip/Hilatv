"""Sample the composed film. Frames stay on disk; the judge receives them later."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.media.ffmpeg import RenderError, run_ffmpeg
from workers.qa.frames import SAMPLE_FPS, sample_frames


def frames_by_shot(
    film: Path,
    spans: list[tuple[str, float, float]],
) -> dict[str, list[Image.Image]]:
    """Assign frames at 4 fps to the shot window that contains each timestamp."""

    frames = sample_frames(film, fps=SAMPLE_FPS)
    grouped: dict[str, list[Image.Image]] = {shot_id: [] for shot_id, _start, _end in spans}
    for index, frame in enumerate(frames):
        timestamp = index / SAMPLE_FPS
        shot_id = _owner(spans, timestamp)
        if shot_id is not None:
            grouped[shot_id].append(frame)
    return grouped


def write_wav(film: Path, dest: Path) -> tuple[Path, bool]:
    """Extract the film's audio. A silent stand-in is used when the file has none.

    The second value is true when the wav is the film's own audio.
    """

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(film),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(dest),
            ]
        )
    except RenderError:
        if dest.exists():
            dest.unlink()
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=16000:cl=mono",
                "-t",
                "0.4",
                str(dest),
            ]
        )
        return dest, False
    return dest, True


def _owner(spans: list[tuple[str, float, float]], timestamp: float) -> str | None:
    for shot_id, start, end in spans:
        if start <= timestamp < end:
            return shot_id
    return None
