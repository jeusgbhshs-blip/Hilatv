"""Benchmark CLI.

``python eval/run_eval.py`` runs all 60 briefs and writes the score table.
Mock mode is the default. ``--mode live`` runs the Temporal film workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.harness import build_report, main  # noqa: E402

__all__ = ["build_report", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
