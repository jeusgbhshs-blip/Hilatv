"""Score table (CSV + Markdown), defect ledger, and the run summary."""

from __future__ import annotations

import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from eval.blind import write_blind
from eval.cases import CASE_COUNT, INDUSTRY_ORDER, PER_INDUSTRY
from eval.qa_port import reviewer_name
from eval.runner import CaseOutcome
from eval.scoring import HARD_INJURY_LIMIT, hard_injury_rate, within_hard_injury_limit

_SCORE_FIELDS = (
    "case_id",
    "industry",
    "score",
    "hard_shots",
    "shot_count",
    "elapsed_s",
    "cost_cny",
    "status",
)

_LEDGER_FIELDS = ("case_id", "shot_id", "node", "model", "shot_type", "defect")


def build_summary(outcomes: list[CaseOutcome], *, mode: str) -> dict[str, Any]:
    rows = [_row(item) for item in outcomes]
    ok = [item for item in outcomes if item.status == "ok" and item.score is not None]
    hard = sum(item.hard_shots for item in outcomes)
    shots = sum(item.shot_count for item in outcomes)
    elapsed = sum((Decimal(str(item.elapsed_s)) for item in outcomes), Decimal("0"))
    cost = sum((Decimal(item.cost_cny or "0") for item in outcomes), Decimal("0"))
    if ok:
        mean = sum((Decimal(str(item.score)) for item in ok), Decimal("0")) / Decimal(len(ok))
        mean_score = float(mean.quantize(Decimal("0.01")))
    else:
        mean_score = None
    rate = hard_injury_rate(hard, shots)
    return {
        "task": "T18",
        "mode": mode,
        "depth": "film" if mode == "live" else "storyboard",
        "reviewer": reviewer_name(),
        "cases": len(outcomes),
        "failed": sum(1 for item in outcomes if item.status != "ok"),
        "shots": shots,
        "hard_shots": hard,
        "hard_injury_rate": float(rate),
        "hard_injury_limit": float(HARD_INJURY_LIMIT),
        "within_hard_injury_limit": within_hard_injury_limit(hard, shots),
        "mean_score": mean_score,
        "total_elapsed_s": float(elapsed.quantize(Decimal("0.001"))),
        "total_cost_cny": format(cost, "f"),
        "rows": rows,
    }


def write_report(out: Path, outcomes: list[CaseOutcome], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = summary["rows"]
    _write_csv(out / "scores.csv", _SCORE_FIELDS, rows)
    _write_ledger(out / "ledger.csv", outcomes)
    (out / "scores.md").write_text(_markdown(summary), encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_blind(out / "blind", outcomes)


def assert_benchmark(summary: dict[str, Any], out: Path) -> None:
    """Structural checks for ``make accept-t18``. Raises ``ValueError`` on a miss."""

    errors: list[str] = []
    if summary.get("cases") != CASE_COUNT:
        errors.append(f"cases {summary.get('cases')} != {CASE_COUNT}")
    if summary.get("failed"):
        failed = [row for row in summary.get("rows") or [] if row.get("status") != "ok"]
        preview = "; ".join(
            f"{row.get('case_id')}: {row.get('error') or row.get('status')}" for row in failed[:8]
        )
        errors.append(f"{summary.get('failed')} cases failed ({preview})")
    counts: Counter[str] = Counter()
    for row in summary.get("rows") or []:
        counts[str(row.get("industry"))] += 1
        for field in _SCORE_FIELDS:
            if field not in row:
                errors.append(f"{row.get('case_id')} missing {field}")
                break
        if row.get("status") == "ok" and row.get("score") is None:
            errors.append(f"{row.get('case_id')} has no score")
    for industry in INDUSTRY_ORDER:
        if counts[industry] != PER_INDUSTRY:
            errors.append(f"{industry} has {counts[industry]} cases")
    if "hard_injury_rate" not in summary:
        errors.append("missing hard_injury_rate")
    elif not summary.get("within_hard_injury_limit"):
        errors.append(
            f"hard injury rate {summary.get('hard_injury_rate')} is above {HARD_INJURY_LIMIT}"
        )
    scores = out / "scores.csv"
    if not scores.is_file():
        errors.append("missing scores.csv")
    else:
        header = scores.read_text(encoding="utf-8").splitlines()[0]
        for field in ("case_id", "score", "hard_shots", "elapsed_s", "cost_cny"):
            if field not in header.split(","):
                errors.append(f"scores.csv missing {field}")
    ledger = out / "ledger.csv"
    if not ledger.is_file():
        errors.append("missing ledger.csv")
    else:
        ledger_header = ledger.read_text(encoding="utf-8").splitlines()[0]
        for field in _LEDGER_FIELDS:
            if field not in ledger_header.split(","):
                errors.append(f"ledger.csv missing {field}")
    pairs_path = out / "blind" / "pairs.json"
    key_path = out / "blind" / "key.json"
    if not pairs_path.is_file() or not key_path.is_file():
        errors.append("blind pack is incomplete")
    else:
        reviewer = pairs_path.read_text(encoding="utf-8")
        leaks = _leaks(reviewer, [str(row.get("case_id")) for row in summary.get("rows") or []])
        if leaks:
            errors.append("reviewer pack leaks " + ", ".join(leaks[:8]))
        payload = json.loads(reviewer)
        if len(payload.get("pairs") or []) != CASE_COUNT:
            errors.append("blind pack does not have 60 pairs")
    if not (out / "scores.md").is_file():
        errors.append("missing scores.md")
    if errors:
        raise ValueError("; ".join(errors))


def _row(outcome: CaseOutcome) -> dict[str, Any]:
    return {
        "case_id": outcome.case_id,
        "industry": outcome.industry,
        "score": outcome.score,
        "hard_shots": outcome.hard_shots,
        "shot_count": outcome.shot_count,
        "elapsed_s": outcome.elapsed_s,
        "cost_cny": outcome.cost_cny,
        "status": outcome.status,
        "error": outcome.error,
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})


def _write_ledger(path: Path, outcomes: list[CaseOutcome]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_LEDGER_FIELDS))
        writer.writeheader()
        for outcome in outcomes:
            for shot in outcome.shots:
                for defect in shot.report.hard_fail:
                    writer.writerow(
                        {
                            "case_id": outcome.case_id,
                            "shot_id": shot.shot_id,
                            "node": shot.node,
                            "model": shot.model,
                            "shot_type": shot.shot_type,
                            "defect": defect,
                        }
                    )


def _markdown(summary: dict[str, Any]) -> str:
    passed = "是" if summary["within_hard_injury_limit"] else "否"
    lines = [
        "# HiLatv 基准评分",
        "",
        f"- 模式：{summary['mode']}（{summary['depth']}）",
        f"- 评审：{summary['reviewer']}",
        f"- 条数：{summary['cases']}，失败：{summary['failed']}",
        f"- 平均分：{summary['mean_score']}",
        f"- 镜头：{summary['shots']}，硬伤镜头：{summary['hard_shots']}",
        (
            f"- 硬伤率：{summary['hard_injury_rate']}（阈值 {summary['hard_injury_limit']}，"
            f"按镜头计，达标：{passed}）"
        ),
        f"- 总耗时（秒）：{summary['total_elapsed_s']}",
        f"- 总费用（元）：{summary['total_cost_cny']}",
        "",
        "| 需求 | 行业 | 分数 | 硬伤镜头数 | 镜头数 | 耗时(秒) | 费用(元) | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {case_id} | {industry} | {score} | {hard_shots} | {shot_count} | "
            "{elapsed_s} | {cost_cny} | {status} |".format(**row)
        )
    lines.append("")
    return "\n".join(lines)


def _leaks(text: str, case_ids: list[str]) -> list[str]:
    folded = text.casefold()
    found: list[str] = []
    for token in ("hilatv", "libtv", "beeftv", "一句成片"):
        if token.casefold() in folded:
            found.append(token)
    for case_id in case_ids:
        if case_id and case_id in text:
            found.append(case_id)
    for industry in INDUSTRY_ORDER:
        if industry in text:
            found.append(industry)
    return found
