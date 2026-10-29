"""Print a stub eval report. The real runner is T18."""

from __future__ import annotations

import json
import sys


def build_report() -> dict[str, object]:
    return {"status": "stub", "task": "T18", "cases": 0, "scores": {}}


def main() -> int:
    json.dump(build_report(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
