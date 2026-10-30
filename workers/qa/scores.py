"""Turn rule findings and two judge opinions into one chapter 5 QAReport."""

from __future__ import annotations

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

_STORYBOARD = {
    "product_fidelity": 8,
    "motion_quality": 8,
    "aesthetics": 8,
    "prompt_match": 8,
    "artifact_free": 10,
}
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


def is_blank(raw: dict[str, object]) -> bool:
    """Mock schema-fill is all zeros. That is no opinion, not a score of zero."""

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


def parse_opinion(raw: object) -> QAReport | None:
    if not isinstance(raw, dict) or is_blank(raw):
        return None
    if str(raw.get("evaluator") or "").startswith("mock"):
        return None
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    if any(name not in scores for name in DIMS):
        return None
    try:
        return QAReport.model_validate(raw)
    except Exception:
        return None


def merge_opinions(left: QAReport | None, right: QAReport | None) -> QAReport | None:
    if left is None:
        return right
    if right is None:
        return left
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


def apply_findings(
    opinion: QAReport | None,
    findings: list[Finding],
    *,
    has_pixels: bool,
) -> QAReport:
    if not has_pixels and not findings:
        if opinion is None:
            return _report(
                _STORYBOARD,
                [],
                evaluator="vlm-judge-v1",
                notes="no pixels; storyboard-only review",
            )
        return _cap_hard(opinion)
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
        hard = _union(hard, opinion.hard_fail)
        for code in opinion.hard_fail:
            _cap(scores, code)
    notes = "; ".join(details) if details else "rules found nothing"
    if opinion is not None and opinion.notes:
        notes = f"{notes}. {opinion.notes}"
    evaluator = "vlm-judge-v1" if opinion is not None else "rule+vlm-v1"
    return _report(scores, hard, evaluator=evaluator, notes=notes)


def _cap(scores: dict[str, int], code: str) -> None:
    for name, limit in _CAPS.get(code, {"artifact_free": 3}).items():
        scores[name] = min(scores[name], limit)


def _cap_hard(report: QAReport) -> QAReport:
    if not report.hard_fail:
        return report
    scores = {name: int(getattr(report.scores, name)) for name in DIMS}
    for code in report.hard_fail:
        _cap(scores, code)
    return _report(scores, report.hard_fail, evaluator=report.evaluator, notes=report.notes)


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
    if codes:
        total = min(total, 6.0)
    return QAReport(
        scores=QAScores.model_validate(clean),
        hard_fail=codes,
        total=total,
        evaluator=evaluator or "vlm-judge-v1",
        notes=notes or "reviewed",
    )
