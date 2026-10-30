"""``hilatv run "一句话"`` produces one master MP4."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from temporalio.client import WorkflowFailureError

from workers.schemas.brand import BrandKit
from workers.workflow.contract import PIPELINE
from workers.workflow.service import run_and_wait, serve_worker
from workers.workflow.store import load_checkpoint, read_snapshot, record_human_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hilatv")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="一句话出片")
    run_parser.add_argument("sentence")
    run_parser.add_argument("--brand-kit", help="Brand Kit JSON 文件")
    run_parser.add_argument("--project-id")

    rerun_parser = sub.add_parser("rerun", help="从某个节点继续，不重跑上游")
    rerun_parser.add_argument("project_id")
    rerun_parser.add_argument("node")

    release_parser = sub.add_parser("release", help="人工放行待复核的成片")
    release_parser.add_argument("project_id")

    sub.add_parser("worker", help="连接 TEMPORAL_ADDRESS，执行活动")

    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "rerun":
            return _cmd_rerun(args)
        if args.command == "release":
            return _cmd_release(args)
        asyncio.run(serve_worker())
        return 0
    except KeyboardInterrupt:
        return 130


def _cmd_run(args: argparse.Namespace) -> int:
    brand = _load_brand(args.brand_kit)
    project_id = args.project_id or str(uuid.uuid4())
    return _execute(project_id=project_id, sentence=args.sentence, brand_kit=brand)


def _cmd_rerun(args: argparse.Namespace) -> int:
    if args.node not in PIPELINE:
        print(f"未知节点 {args.node}", file=sys.stderr)
        return 2
    snapshot = read_snapshot(args.project_id)
    if snapshot is None:
        print("项目不存在", file=sys.stderr)
        return 2
    if snapshot.get("status") == "running":
        print("项目仍在运行", file=sys.stderr)
        return 2
    checkpoint = None if args.node == PIPELINE[0] else load_checkpoint(args.project_id)
    return _execute(
        project_id=args.project_id,
        sentence=str(snapshot.get("sentence") or ""),
        brand_kit=snapshot.get("brand_kit"),
        brand_id=snapshot.get("brand_id"),
        attachments=snapshot.get("attachments") or [],
        keyframe_candidates=snapshot.get("keyframe_candidates"),
        video_candidates=snapshot.get("video_candidates"),
        start_from=args.node,
        checkpoint=checkpoint,
    )


def _cmd_release(args: argparse.Namespace) -> int:
    snapshot = read_snapshot(args.project_id)
    if snapshot is None:
        print("项目不存在", file=sys.stderr)
        return 2
    if snapshot.get("status") != "needs_human_review":
        print("项目不在人工复核", file=sys.stderr)
        return 2
    record_human_release(args.project_id)
    return _execute(
        project_id=args.project_id,
        sentence=str(snapshot.get("sentence") or ""),
        brand_kit=snapshot.get("brand_kit"),
        brand_id=snapshot.get("brand_id"),
        enterprise_id=snapshot.get("enterprise_id"),
        concept_selection=snapshot.get("concept_selection"),
        attachments=snapshot.get("attachments") or [],
        keyframe_candidates=snapshot.get("keyframe_candidates"),
        video_candidates=snapshot.get("video_candidates"),
        start_from="n12_music",
        checkpoint=load_checkpoint(args.project_id),
        human_release=True,
    )


def _execute(**kwargs: Any) -> int:
    project_id = str(kwargs["project_id"])
    try:
        result = asyncio.run(run_and_wait(**kwargs))
    except WorkflowFailureError as exc:
        _print_result({"project_id": project_id, "status": "failed", "error": str(exc)[:500]})
        print(str(exc), file=sys.stderr)
        return 1
    status = str(result.get("status") or "completed")
    _print_result(
        {
            "project_id": project_id,
            "status": status,
            "deliverable": result.get("deliverable"),
            "elapsed_s": result.get("elapsed_s"),
            "timing_recorded": True,
            "live": bool(result.get("live")),
            "phase": "待人工复核" if status == "needs_human_review" else "成片",
        }
    )
    return 0


def _print_result(payload: dict[str, Any]) -> None:
    print("HILATV_RESULT " + json.dumps(payload, ensure_ascii=False))


def _load_brand(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        kit = BrandKit.model_validate(raw)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    return kit.model_dump(mode="json")


if __name__ == "__main__":
    raise SystemExit(main())
