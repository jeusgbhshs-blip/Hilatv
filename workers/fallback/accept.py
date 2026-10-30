"""Fault-injection film. The video model fails; the master still plays.

Per-level checks live in ``workers/fallback/tests``. This command is the workflow
run: every shot's video adapter raises, and the delivered file is decoded with
ffprobe and ffmpeg.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    os.environ["HILATV_FAIL_VIDEO_SHOTS"] = "*"
    os.environ["HILATV_LIVE"] = "0"
    os.environ["HILATV_RENDER_WIDTH"] = "320"
    os.environ["HILATV_RENDER_HEIGHT"] = "180"
    os.environ["HILATV_BUDGET_CNY"] = "0"
    os.environ["HILATV_DAILY_BUDGET_CNY"] = "0"
    for name in (
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "MINIO_ENDPOINT",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_BUCKET",
        "DASHSCOPE_API_KEY",
        "GEMINI_API_KEY",
    ):
        os.environ.pop(name, None)

    from workers.workflow.service import run_and_wait
    from workers.workflow.store import load_checkpoint

    project_id = "t14e2e"
    result = asyncio.run(
        run_and_wait(
            project_id=project_id,
            sentence="给柱塞泵做个5秒中文宣传片，风格稳重",
        )
    )
    if not result.get("deliverable"):
        print("workflow returned no deliverable", file=sys.stderr)
        return 1
    master = Path(str(result["deliverable"]))
    info = _probe(master)
    _decode(master)
    state = load_checkpoint(project_id)
    notes = state.get("shot_quality") or []
    if not isinstance(notes, list) or not notes:
        print("delivery has no shot quality notes", file=sys.stderr)
        return 1
    timeline_path = state.get("timeline_path")
    timeline = json.loads(Path(str(timeline_path)).read_text(encoding="utf-8"))
    script = state.get("script") or {}
    shots = script.get("shots") or []
    clip_ids = [item.get("clip_id") for item in timeline.get("clips") or []]
    picture = [item for item in clip_ids if item not in {"intro", "outro"}]
    duration = float(info["duration_s"])
    expected = float(timeline["duration_s"])
    levels = [int(item.get("fallback_level") or 0) for item in notes]
    blob = json.dumps(notes, ensure_ascii=False)
    if "建议补拍" in blob:
        print("delivery asked for a reshoot", file=sys.stderr)
        return 1
    if any(level not in {3, 4} for level in levels):
        print(f"expected AI levels 3 or 4, got {levels}", file=sys.stderr)
        return 1
    if picture != [shot.get("shot_id") for shot in shots]:
        print(f"shot clips {picture} do not match the script", file=sys.stderr)
        return 1
    if abs(duration - expected) > 0.2:
        print(f"duration {duration} != timeline {expected}", file=sys.stderr)
        return 1
    if any(item.get("qa_passed") or item.get("reviewed") for item in notes):
        print("a downgraded shot was reported as passed or reviewed", file=sys.stderr)
        return 1
    delta = _frame_delta(notes)
    print(
        "accept-t14 e2e "
        f"duration_s={duration:.3f} timeline_s={expected:.3f} "
        f"shots={len(picture)} levels={levels} "
        f"codec={info['codec']} reshoot=absent "
        f"flat_mock_frame_delta={delta} live_vlm=未测"
    )
    return 0


def _frame_delta(notes: list[dict[str, object]]) -> str:
    """0 means the mock keyframe was a flat color, so the zoom is not visible."""

    from workers.qa.frames import sample_frames

    changed = 0
    checked = 0
    for item in notes:
        if item.get("fallback_level") != 3:
            continue
        path = Path(str(item.get("media_path") or ""))
        if not path.is_file():
            continue
        frames = sample_frames(path)
        if len(frames) < 2:
            continue
        checked += 1
        if frames[0].tobytes() != frames[-1].tobytes():
            changed += 1
    if checked == 0:
        return "未测"
    return f"{changed}/{checked}"


def _probe(path: Path) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        print(f"missing master {path}", file=sys.stderr)
        raise SystemExit(1)
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(1)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_name")), {})
    codec = video.get("codec_name")
    if codec != "h264":
        print(f"expected h264, got {codec}", file=sys.stderr)
        raise SystemExit(1)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        print("master duration is 0", file=sys.stderr)
        raise SystemExit(1)
    return {
        "codec": codec,
        "duration_s": duration,
        "width": video.get("width"),
        "height": video.get("height"),
    }


def _decode(path: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr[-400:], file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
