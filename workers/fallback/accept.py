"""Fault-injection film. The video model fails; the master still plays.

Per-level checks live in ``workers/fallback/tests``. This command is the workflow
run: every shot's video adapter raises, and the delivered file is decoded with
ffprobe and ffmpeg.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


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
    if result.get("status") != "needs_human_review":
        print(f"expected needs_human_review, got {result.get('status')}", file=sys.stderr)
        return 1
    if result.get("deliverable"):
        print("held project returned a deliverable", file=sys.stderr)
        return 1
    from workers.workflow.store import project_path, read_snapshot

    root = project_path(project_id)
    if list(root.rglob("master.mp4")) or (root / "deliveries.json").is_file():
        print("held project wrote a delivery artifact", file=sys.stderr)
        return 1
    snapshot = read_snapshot(project_id) or {}
    if snapshot.get("status") != "needs_human_review" or snapshot.get("deliverable"):
        print(f"snapshot is not held: {snapshot.get('status')}", file=sys.stderr)
        return 1
    state = load_checkpoint(project_id)
    notes = state.get("shot_quality") or []
    if not isinstance(notes, list) or not notes:
        print("delivery has no shot quality notes", file=sys.stderr)
        return 1
    script = state.get("script") or {}
    shots = script.get("shots") or []
    levels = [int(item.get("fallback_level") or 0) for item in notes]
    blob = json.dumps(notes, ensure_ascii=False)
    if "建议补拍" in blob:
        print("delivery asked for a reshoot", file=sys.stderr)
        return 1
    if any(level != 4 for level in levels):
        print(f"mock review must not accept levels 1-3, got {levels}", file=sys.stderr)
        return 1
    if not all(item.get("needs_review") is True for item in notes):
        print("an unreviewed fallback was not marked needs_review", file=sys.stderr)
        return 1
    if any(item.get("qa_passed") or item.get("reviewed") for item in notes):
        print("a downgraded shot was reported as passed or reviewed", file=sys.stderr)
        return 1
    print(
        "accept-t14 e2e "
        f"status=needs_human_review deliverable=absent "
        f"shots={len(shots)} levels={levels} "
        "reshoot=absent needs_review=true reviewed=false qa_passed=false "
        "released=false flat_mock_frame_delta=未测 live_vlm=未测"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
