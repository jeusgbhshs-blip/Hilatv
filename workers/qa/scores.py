"""Turn rule findings and two judge opinions into one chapter 5 QAReport."""

from __future__ import annotations

from dataclasses import dataclass

from workers.qa.rules import Finding
from workers.schemas.asset import QAReport, QAScores

PASS_TOTAL = 7.5
DIMS = (
    "product_fidelity",
    "motion_quality",
    "aesthetics",
    "prompt_match",
    "artifact_free",
)
DISAGREE = 2.0

_BASE = {
    "product_fidelity": 9,
    "motion_quality": 8,
    "aesthetics": 8,
    "prompt_match": 9,
    "artifact_free": 9,
}
_CAPS: dict[str, dict[str, int]] = {
    "product_deform": {"product_fidelity": 2, "artifact_free": 3},
    "extra_text": {"artifact_free": 2, "aesthetics": 4, "prompt_match": 4},
    "garbled_text": {"artifact_free": 1, "aesthetics": 3},
    "face_collapse": {"artifact_free": 1, "product_fidelity": 3},
    "face_count": {"artifact_free": 2, "product_fidelity": 4},
    "face_inconsistent": {"product_fidelity": 3, "motion_quality": 3},
    "black_bar": {"aesthetics": 3, "artifact_free": 4},
    "watermark": {"artifact_free": 2, "aesthetics": 4},
    "low_resolution": {"aesthetics": 3, "prompt_match": 5},
    "bad_composition": {"aesthetics": 3, "prompt_match": 4},
    "flicker": {"motion_quality": 2, "artifact_free": 3},
    "sensitive": {"artifact_free": 0, "aesthetics": 2},
}


@dataclass
class ParsedOpinion:
    report: QAReport | None
    error: str | None


@dataclass
class JudgeReview:
    opinion: QAReport | None
    judges_used: int
    degraded: bool
    mock: bool
    live_unavailable: bool
    detail: str


def is_blank(raw: dict[str, object]) -> bool:
    """Mock schema-fill is all zeros. That is not a score of zero."""

    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    try:
        numbers = [int(scores.get(name) or 0) for name in DIMS]  # type: ignore[union-attr]
        total = float(raw.get("total") or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return (
        str(raw.get("evaluator") or "") in {"", "mock"}
        and str(raw.get("notes") or "") in {"", "mock"}
        and not raw.get("hard_fail")
        and all(number == 0 for number in numbers)
        and total == 0.0
    )


def parse_opinion(raw: object) -> ParsedOpinion:
    """A judge payload is valid only when every dimension is present. Nothing is filled in."""

    if not isinstance(raw, dict):
        return ParsedOpinion(None, "parse_failure")
    if is_blank(raw) or str(raw.get("evaluator") or "").startswith("mock"):
        return ParsedOpinion(None, "mock")
    scores = raw.get("scores")
    if not isinstance(scores, dict) or any(name not in scores for name in DIMS):
        return ParsedOpinion(None, "missing_dimensions")
    try:
        return ParsedOpinion(QAReport.model_validate(raw), None)
    except Exception:
        return ParsedOpinion(None, "parse_failure")


def combine_judges(primary: ParsedOpinion, cross: ParsedOpinion, *, live: bool) -> JudgeReview:
    valid = [item for item in (primary, cross) if item.report is not None]
    if len(valid) == 2 and primary.report is not None and cross.report is not None:
        merged = merge_opinions(primary.report, cross.report)
        return JudgeReview(
            merged,
            2,
            False,
            False,
            False,
            "judges_used=2; degraded=false; primary=ok; cross=ok",
        )
    if len(valid) == 1:
        kept = "primary" if primary.report is not None else "cross"
        other = cross if kept == "primary" else primary
        other_name = "cross" if kept == "primary" else "primary"
        detail = (
            f"judges_used=1; degraded=true; kept={kept}; {other_name}={other.error or 'invalid'}"
        )
        return JudgeReview(valid[0].report, 1, True, False, False, detail)
    detail = f"judges_used=0; degraded=true; primary={primary.error}; cross={cross.error}"
    if live:
        return JudgeReview(None, 0, True, False, True, detail)
    return JudgeReview(None, 0, True, True, False, f"{detail}; judge=mock; quality_pass=false")


def merge_opinions(left: QAReport, right: QAReport) -> QAReport:
    hard = _union(left.hard_fail, right.hard_fail)
    if abs(left.total - right.total) >= DISAGREE:
        scores = {
            name: min(getattr(left.scores, name), getattr(right.scores, name)) for name in DIMS
        }
        notes = "cross-review disagreed; kept the stricter scores"
    else:
        scores = {
            name: int(round((getattr(left.scores, name) + getattr(right.scores, name)) / 2))
            for name in DIMS
        }
        notes = "cross-review agreed"
    return _report(scores, hard, evaluator="vlm-judge-v1", notes=notes)


def not_reviewed(kind: str, reason: str) -> QAReport:
    """No pixels to score. ``kind`` is text_only, missing, broken, or unreadable."""

    notes = (
        f"not_reviewed; media={kind}; reason={reason}; "
        "judges_used=0; degraded=true; quality_pass=false"
    )
    return _zeros(["not_reviewed"], evaluator="not-reviewed", notes=notes)


def judge_unavailable(detail: str, findings: list[Finding]) -> QAReport:
    """Pixels existed, but no vision judge scored them. Not a pass."""

    return _unavailable("judge_unavailable", detail, findings)


def _unavailable(code: str, detail: str, findings: list[Finding]) -> QAReport:
    codes = [code]
    extra: list[str] = []
    for finding in findings:
        if finding.code not in codes:
            codes.append(finding.code)
        extra.append(f"{finding.code}: {finding.detail}")
    notes = f"{detail}; quality_pass=false"
    if extra:
        notes = f"{notes}; {'; '.join(extra)}"
    return _zeros(codes, evaluator="judge-unavailable", notes=notes)


def apply_findings(
    review: JudgeReview,
    findings: list[Finding],
    *,
    has_pixels: bool,
    pixels_shown: bool,
) -> QAReport:
    """Rule-only scores are not a pass. A pass needs a judge that saw the frame."""

    if not has_pixels:
        return not_reviewed("missing", "no pixels")
    saw_frame = (
        pixels_shown
        and review.judges_used >= 1
        and review.opinion is not None
        and not review.mock
        and not review.live_unavailable
    )
    if not saw_frame:
        detail = review.detail or "judge gave no opinion"
        if "quality_pass=false" not in detail:
            detail = f"{detail}; quality_pass=false"
        return judge_unavailable(detail, findings)
    report = _from_rules(findings, review.opinion)
    passed = not report.hard_fail and report.total >= PASS_TOTAL
    notes = f"{review.detail}; quality_pass={'true' if passed else 'false'}"
    if report.notes:
        notes = f"{notes}; {report.notes}"
    return report.model_copy(
        update={
            "evaluator": "vlm-judge-v1",
            "notes": notes,
            "visual_reviewed": True,
            "judges_used": review.judges_used,
            "degraded": review.degraded,
        }
    )


CONTENT_SAFETY = frozenset({"sensitive"})


def content_blocked(report: QAReport) -> bool:
    """A content-safety hard fail is not allowed into the master."""

    return any(code in CONTENT_SAFETY for code in report.hard_fail)


def is_quality_pass(report: QAReport) -> bool:
    """A calibrated pass. Mock judges and unreviewable shots never qualify."""

    if not report.visual_reviewed:
        return False
    if report.hard_fail or report.total < PASS_TOTAL:
        return False
    if report.evaluator.startswith("mock"):
        return False
    if report.evaluator in {"not-reviewed", "judge-unavailable"}:
        return False
    if "quality_pass=false" in report.notes:
        return False
    return True


def _from_rules(findings: list[Finding], opinion: QAReport | None) -> QAReport:
    scores = dict(_BASE)
    hard: list[str] = []
    details: list[str] = []
    for finding in findings:
        hard.append(finding.code)
        details.append(f"{finding.code}: {finding.detail}")
        _cap(scores, finding.code)
    if opinion is not None:
        for name in DIMS:
            scores[name] = min(scores[name], int(getattr(opinion.scores, name)))
        hard = _union(hard, list(opinion.hard_fail))
        for code in opinion.hard_fail:
            _cap(scores, code)
    notes = "; ".join(details) if details else "rules found nothing"
    if opinion is not None and opinion.notes:
        notes = f"{notes}. {opinion.notes}"
    return _report(scores, hard, evaluator="vlm-judge-v1", notes=notes)


def _zeros(hard: list[str], *, evaluator: str, notes: str) -> QAReport:
    return QAReport(
        scores=QAScores(
            product_fidelity=0,
            motion_quality=0,
            aesthetics=0,
            prompt_match=0,
            artifact_free=0,
        ),
        hard_fail=_union(hard, []),
        total=0,
        evaluator=evaluator,
        notes=notes,
        visual_reviewed=False,
        judges_used=0,
        degraded=False,
    )


def _cap(scores: dict[str, int], code: str) -> None:
    for name, limit in _CAPS.get(code, {"artifact_free": 3}).items():
        scores[name] = min(scores[name], limit)


def _union(left: list[str], right: list[str]) -> list[str]:
    found: list[str] = []
    for item in [*left, *right]:
        text = str(item).strip()
        if text and text not in found:
            found.append(text)
    return found


def _report(
    scores: dict[str, int],
    hard: list[str],
    *,
    evaluator: str,
    notes: str,
) -> QAReport:
    clean = {name: max(0, min(10, int(scores[name]))) for name in DIMS}
    total = round(sum(clean.values()) / len(DIMS), 1)
    codes = _union(hard, [])
    if "not_reviewed" in codes or "judge_unavailable" in codes:
        clean = {name: 0 for name in DIMS}
        total = 0.0
    elif codes:
        total = min(total, 6.0)
    return QAReport(
        scores=QAScores.model_validate(clean),
        hard_fail=codes,
        total=total,
        evaluator=evaluator or "vlm-judge-v1",
        notes=notes or "reviewed",
        visual_reviewed=False,
    )
