"""One command runs the benchmark and writes the score table."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from eval.cases import load_cases
from eval.report import assert_benchmark, build_summary, write_report
from eval.runner import CaseOutcome, run_case
from gateway.service import get_gateway, reset_gateway


def build_report(summary: dict[str, Any] | None = None) -> dict[str, Any]:
    if summary is None:
        return {"status": "ready", "task": "T18", "cases": 0, "scores": {}}
    payload = dict(summary)
    payload["task"] = "T18"
    return payload


def execute(cases: list[Any], *, mode: str, gateway: Any | None = None) -> list[CaseOutcome]:
    gateway = gateway or get_gateway()
    outcomes: list[CaseOutcome] = []
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        outcome = run_case(case, mode=mode, gateway=gateway)
        outcomes.append(outcome)
        detail = outcome.error or f"score={outcome.score} shots={outcome.shot_count}"
        print(
            f"[{index}/{total}] {outcome.case_id} {outcome.status} {detail} "
            f"{outcome.elapsed_s}s ¥{outcome.cost_cny}",
            file=sys.stderr,
        )
    return outcomes


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="eval/run_eval.py")
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default=os.getenv("HILATV_EVAL_MODE", "mock").strip() or "mock",
    )
    parser.add_argument("--out", default=os.getenv("HILATV_EVAL_OUT", "").strip())
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "live":
        os.environ["HILATV_LIVE"] = "1"
    else:
        os.environ["HILATV_LIVE"] = "0"
    reset_gateway()

    cases = load_cases()
    if args.limit > 0:
        cases = cases[: args.limit]
    out = Path(args.out) if args.out else Path("eval/reports/latest")
    outcomes = execute(cases, mode=args.mode)
    summary = build_summary(outcomes, mode=args.mode)
    write_report(out, outcomes, summary)
    conclusions = summary["conclusions"]
    short = {
        "task": "T18",
        "mode": args.mode,
        "cases": summary["cases"],
        "failed": summary["failed"],
        "shots": summary["shots"],
        "reviewed_shots": summary["reviewed_shots"],
        "unreviewed_shots": summary["unreviewed_shots"],
        "text_only_shots": summary["text_only_shots"],
        "invalid_shots": summary["invalid_shots"],
        "review_error_shots": summary["review_error_shots"],
        "reviewer": summary["reviewer"],
        "hard_shots": summary["hard_shots"],
        "hard_injury_rate": summary["hard_injury_rate"],
        "mean_score": summary["mean_score"],
        "pipeline_complete": summary["pipeline_complete"],
        "pipeline_label": conclusions["pipeline"]["label"],
        "quality_met": summary["quality_met"],
        "quality_label": conclusions["quality"]["label"],
        "total_elapsed_s": summary["total_elapsed_s"],
        "total_cost_cny": summary["total_cost_cny"],
        "out": str(out),
    }
    print("HILATV_EVAL " + json.dumps(short, ensure_ascii=False))
    if summary["failed"]:
        return 1
    if args.strict:
        try:
            if args.limit:
                raise ValueError("--strict runs the full 60-case set")
            assert_benchmark(summary, out)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    return 0
