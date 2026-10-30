"""Rerun N14 by itself: ``python -m workers.nodes.n14_packaging --input request.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from workers.nodes.n14_packaging.node import run
from workers.nodes.n14_packaging.qa import QAError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run N14 packaging once")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    try:
        result = run(raw, timeout_s=args.timeout, max_attempts=args.max_attempts)
    except (ValidationError, QAError, TimeoutError, ValueError) as exc:
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
