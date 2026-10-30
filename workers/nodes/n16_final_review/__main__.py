"""Rerun N16 final review by itself: ``python -m workers.nodes.n16_final_review``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from workers.nodes.n16_final_review.node import run
from workers.nodes.n16_final_review.qa import QAError
from workers.schemas.label_lock import LabelLocked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run N16 final review once")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(raw.get("payload"), dict):
        raw["payload"].pop("enterprise_id", None)
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


if __name__ == "__main__":
    raise SystemExit(main())
