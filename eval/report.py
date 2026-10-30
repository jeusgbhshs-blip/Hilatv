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
from eval.qa_port import TEXT_ONLY_LABEL, review_port
from eval.runner import CaseOutcome
from eval.scoring import HARD_INJURY_LIMIT, ShotScore, hard_injury_rate, within_hard_injury_limit

_SCORE_FIELDS = (
    "case_id",
    "industry",
    "score",
    "hard_shots",
    "shot_count",
    "reviewed_shots",
    "unreviewed_shots",
    "text_only_shots",
    "invalid_shots",
    "elapsed_s",
    "cost_cny",
    "status",
)

_LEDGER_FIELDS = ("case_id", "shot_id", "node", "model", "shot_type", "defect")


def build_summary(outcomes: list[CaseOutcome], *, mode: str) -> dict[str, Any]:
    rows = [_row(item) for item in outcomes]
    counted = [item for item in outcomes if item.status == "ok" and _fully_reviewed(item)]
    tallies = [_tally(item) for item in outcomes]
    hard = sum(item[4] for item in tallies)
    shots = sum(item.shot_count for item in outcomes)
    reviewed = sum(item[0] for item in tallies)
    unreviewed = sum(item[1] for item in tallies)
    text_only = sum(item[2] for item in tallies)
    invalid = sum(item[3] for item in tallies)
    elapsed = sum((Decimal(str(item.elapsed_s)) for item in outcomes), Decimal("0"))
    cost = sum((Decimal(item.cost_cny or "0") for item in outcomes), Decimal("0"))
    if counted:
        total = sum((Decimal(str(item.score)) for item in counted), Decimal("0"))
        mean = total / Decimal(len(counted))
        mean_score: float | None = float(mean.quantize(Decimal("0.01")))
    else:
        mean_score = None
    if reviewed:
        rate: float | None = float(hard_injury_rate(hard, reviewed))
    else:
        rate = None
    fully = shots > 0 and reviewed == shots and unreviewed == 0 and text_only == 0 and invalid == 0
    hard_over = reviewed > 0 and not within_hard_injury_limit(hard, reviewed)
    injury_ok = fully and not hard_over
    quality_met = injury_ok
    pipeline_complete = _pipeline_complete(outcomes)
    conclusions = {
        "pipeline": {
            "met": pipeline_complete,
            "label": "管线和报告结构完整" if pipeline_complete else "管线和报告结构不完整",
        },
        "quality": _quality_conclusion(
            met=quality_met,
            unreviewed=unreviewed,
            text_only=text_only,
            invalid=invalid,
            reviewed=reviewed,
            rate=rate,
            hard_over=hard_over,
            shots=shots,
        ),
    }
    return {
        "task": "T18",
        "mode": mode,
        "depth": "film" if mode == "live" else "storyboard",
        "review_port": review_port(),
        "reviewer": _reviewer(reviewed, shots),
        "review_note": _review_note(reviewed, shots, text_only, unreviewed),
        "cases": len(outcomes),
        "failed": sum(1 for item in outcomes if item.status != "ok"),
        "shots": shots,
        "reviewed_shots": reviewed,
        "unreviewed_shots": unreviewed,
        "text_only_shots": text_only,
        "invalid_shots": invalid,
        "hard_shots": hard,
        "hard_injury_rate": rate,
        "hard_injury_basis": "reviewed" if reviewed else "none",
        "hard_injury_limit": float(HARD_INJURY_LIMIT),
        "within_hard_injury_limit": injury_ok,
        "mean_score": mean_score,
        "pipeline_complete": pipeline_complete,
        "quality_met": quality_met,
        "conclusions": conclusions,
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
    """Pipeline and report shape for ``make accept-t18``.

    Quality is a separate conclusion. An unreviewed shot must not be reported
    as a quality pass. That does not by itself fail this check: mock runs have
    no pixels and no T12 reviewer, and CI still has to execute the harness.
    """

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
        if row.get("status") == "ok" and not row.get("shot_count"):
            errors.append(f"{row.get('case_id')} has no shots")
    for industry in INDUSTRY_ORDER:
        if counts[industry] != PER_INDUSTRY:
            errors.append(f"{industry} has {counts[industry]} cases")
    for key in ("hard_injury_rate", "unreviewed_shots", "reviewer", "review_note", "conclusions"):
        if key not in summary:
            errors.append(f"missing {key}")
    conclusions = summary.get("conclusions") if isinstance(summary.get("conclusions"), dict) else {}
    pipeline = conclusions.get("pipeline") if isinstance(conclusions.get("pipeline"), dict) else {}
    quality = conclusions.get("quality") if isinstance(conclusions.get("quality"), dict) else {}
    if "met" not in pipeline or "label" not in pipeline:
        errors.append("missing pipeline conclusion")
    elif pipeline.get("met") is not summary.get("pipeline_complete"):
        errors.append("pipeline conclusion does not match pipeline_complete")
    if "met" not in quality or "label" not in quality:
        errors.append("missing quality conclusion")
    elif quality.get("met") is not summary.get("quality_met"):
        errors.append("quality conclusion does not match quality_met")
    unreviewed = int(summary.get("unreviewed_shots") or 0)
    text_only = int(summary.get("text_only_shots") or 0)
    invalid = int(summary.get("invalid_shots") or 0)
    if (unreviewed or text_only or invalid) and summary.get("quality_met"):
        errors.append("未评审不能算通过")
    if text_only and TEXT_ONLY_LABEL not in json.dumps(summary, ensure_ascii=False):
        errors.append("text-only review is not labeled")
    if int(summary.get("reviewed_shots") or 0) == 0 and summary.get("mean_score") is not None:
        errors.append("mean score without a reviewed shot")
    if summary.get("reviewer") == "mock-judge":
        errors.append("reviewer must not be the hardcoded mock-judge profile")
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
    reviewed, unreviewed, text_only, invalid, hard = _tally(outcome)
    score = outcome.score if _fully_reviewed(outcome) else None
    return {
        "case_id": outcome.case_id,
        "industry": outcome.industry,
        "score": score,
        "hard_shots": hard,
        "shot_count": outcome.shot_count,
        "reviewed_shots": reviewed,
        "unreviewed_shots": unreviewed,
        "text_only_shots": text_only,
        "invalid_shots": invalid,
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
                if shot.report is None:
                    continue
                if shot.review_status != "reviewed":
                    continue
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
    conclusions = summary["conclusions"]
    rate = summary["hard_injury_rate"]
    rate_text = "—" if rate is None else str(rate)
    lines = [
        "# HiLatv 基准评分",
        "",
        f"- 模式：{summary['mode']}（{summary['depth']}）",
        f"- 评审来源：{summary['reviewer']}（端口 {summary['review_port']}）",
        f"- 评审说明：{summary['review_note']}",
        f"- 结论：{conclusions['pipeline']['label']}",
        f"- 结论：{conclusions['quality']['label']}",
    ]
    reasons = conclusions["quality"].get("reasons") or []
    if reasons:
        lines.append("- 质量原因：" + "；".join(str(item) for item in reasons))
    lines.extend(
        [
            f"- 条数：{summary['cases']}，失败：{summary['failed']}",
            f"- 平均分：{_cell(summary['mean_score'])}",
            (
                f"- 镜头：{summary['shots']}，已评审：{summary['reviewed_shots']}，"
                f"未评审：{summary['unreviewed_shots']}，只评文字：{summary['text_only_shots']}，"
                f"无效：{summary['invalid_shots']}"
            ),
            f"- 硬伤镜头：{summary['hard_shots']}（只统计已评审镜头）",
            (
                f"- 硬伤率：{rate_text}（阈值 {summary['hard_injury_limit']}，"
                f"分母是已评审镜头，质量达标：{'是' if summary['quality_met'] else '否'}）"
            ),
            f"- 总耗时（秒）：{summary['total_elapsed_s']}",
            f"- 总费用（元）：{summary['total_cost_cny']}",
            "",
            "| 需求 | 行业 | 分数 | 硬伤镜头数 | 镜头数 | 未评审 | 耗时(秒) | 费用(元) | 状态 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["rows"]:
        lines.append(
            "| {case_id} | {industry} | {score} | {hard_shots} | {shot_count} | "
            "{unreviewed_shots} | {elapsed_s} | {cost_cny} | {status} |".format(
                **{key: _cell(value) for key, value in row.items()}
            )
        )
    lines.append("")
    return "\n".join(lines)


def _pipeline_complete(outcomes: list[CaseOutcome]) -> bool:
    if len(outcomes) != CASE_COUNT:
        return False
    if any(item.status != "ok" or item.shot_count <= 0 for item in outcomes):
        return False
    counts: Counter[str] = Counter(item.industry for item in outcomes)
    return all(counts[industry] == PER_INDUSTRY for industry in INDUSTRY_ORDER)


def _quality_conclusion(
    *,
    met: bool,
    unreviewed: int,
    text_only: int,
    invalid: int,
    reviewed: int,
    rate: float | None,
    hard_over: bool,
    shots: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    if unreviewed:
        reasons.append(f"未评审 {unreviewed} 镜，不能算通过")
    if text_only:
        reasons.append(TEXT_ONLY_LABEL)
    if invalid:
        reasons.append(f"无效评分 {invalid} 镜")
    if hard_over:
        reasons.append(f"已评审镜头硬伤率 {rate} 超过 {HARD_INJURY_LIMIT}")
    if shots == 0:
        reasons.append("没有镜头")
    elif reviewed == 0 and not reasons:
        reasons.append("没有可计入质量结论的评审")
    return {
        "met": met,
        "label": "质量达标" if met else "质量未达标",
        "reasons": reasons,
    }


def _reviewer(reviewed: int, shots: int) -> str:
    port = review_port()
    if shots and reviewed == shots:
        return port
    if reviewed == 0:
        return "unreviewed"
    return "mixed"


def _review_note(reviewed: int, shots: int, text_only: int, unreviewed: int) -> str:
    if shots and reviewed == shots and review_port() == "t12":
        return "评审来自 T12 review_shot。"
    if shots and reviewed == shots:
        return "评审来自网关，调用时传入了关键帧或视频引用。"
    if text_only and text_only == shots:
        return (
            "T12 的 review_shot 不存在，镜头没有关键帧或视频。"
            f"备用评审没有把分镜文字当成画面分。{TEXT_ONLY_LABEL}。"
        )
    if unreviewed:
        return (
            "T12 的 review_shot 不存在，或网关没有返回真实视觉评审。"
            "未评审镜头不计入质量结论。" + (TEXT_ONLY_LABEL + "。" if text_only else "")
        )
    return "没有可计入质量结论的评审。"


def _fully_reviewed(outcome: CaseOutcome) -> bool:
    if outcome.status != "ok" or outcome.shot_count <= 0 or outcome.score is None:
        return False
    if outcome.shots:
        return all(
            shot.review_status == "reviewed" and shot.report is not None for shot in outcome.shots
        )
    return (
        outcome.reviewed_shots == outcome.shot_count
        and outcome.unreviewed_shots == 0
        and outcome.text_only_shots == 0
        and outcome.invalid_shots == 0
    )


def _tally(outcome: CaseOutcome) -> tuple[int, int, int, int, int]:
    if outcome.shots:
        reviewed = sum(1 for shot in outcome.shots if _is_reviewed(shot))
        text_only = sum(1 for shot in outcome.shots if shot.review_status == "text_only")
        invalid = sum(1 for shot in outcome.shots if shot.review_status == "invalid")
        bare = sum(1 for shot in outcome.shots if shot.review_status == "unreviewed")
        hard = sum(1 for shot in outcome.shots if _injured(shot))
        return reviewed, bare + text_only, text_only, invalid, hard
    return (
        outcome.reviewed_shots,
        outcome.unreviewed_shots,
        outcome.text_only_shots,
        outcome.invalid_shots,
        outcome.hard_shots,
    )


def _is_reviewed(shot: ShotScore) -> bool:
    return shot.review_status == "reviewed" and shot.report is not None


def _injured(shot: ShotScore) -> bool:
    return _is_reviewed(shot) and bool(shot.report and shot.report.hard_fail)


def _cell(value: object) -> str:
    if value is None:
        return "—"
    return str(value)


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
