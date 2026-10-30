"""Rerun N16 final review by itself: ``python -m workers.nodes.n16_final_review``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from workers.identity.access import AccessError, Conflict, NotFound, project_for
from workers.identity.session import Identity, SessionError, verify_session
from workers.nodes.n16_final_review.node import run
from workers.nodes.n16_final_review.qa import QAError
from workers.schemas.label_lock import LabelLocked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run N16 final review once")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--session", help="登录会话。缺省时读 HILATV_SESSION")
    args = parser.parse_args(argv)
    identity = _identity(args.session)
    if identity is None:
        return 2
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(raw.get("payload"), dict):
        raw["payload"].pop("enterprise_id", None)
    project_id = raw.get("project_id")
    if not isinstance(project_id, str) or _owned(project_id, identity) is None:
        return 2
    try:
        result = run(raw, timeout_s=args.timeout, max_attempts=args.max_attempts)
    except (ValidationError, QAError, TimeoutError, ValueError, LabelLocked) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def _identity(session: str | None) -> Identity | None:
    token = (session or os.getenv("HILATV_SESSION", "")).strip()
    if not token:
        print("需要登录会话", file=sys.stderr)
        return None
    try:
        return verify_session(token)
    except SessionError:
        print("会话无效", file=sys.stderr)
        return None


def _owned(project_id: str, identity: Identity) -> dict | None:
    try:
        return project_for(identity, project_id)
    except NotFound:
        print("项目不存在", file=sys.stderr)
        return None
    except Conflict as exc:
        print(exc.detail, file=sys.stderr)
        return None
    except AccessError as exc:
        print(exc.detail, file=sys.stderr)
        return None


if __name__ == "__main__":
    raise SystemExit(main())
