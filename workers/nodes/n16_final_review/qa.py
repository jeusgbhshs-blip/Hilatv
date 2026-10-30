"""N16 final-review checks. A release without a real review is rejected in live mode."""

from __future__ import annotations

from workers.nodes.n16_final_review.schema import FilmIssue, NodeResult
from workers.schemas.asset import QAReport
from workers.schemas.director import DecisionAction, DirectorDecision

_REGEN = {DecisionAction.regenerate, DecisionAction.switch_model}
_FORBIDDEN = (
    "补拍",
    "实拍",
    "客户素材",
    "reshoot",
    "customer_footage",
    "omit_ai_label",
    "hide_ai_label",
)


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> dict:
    if result.node != "n16_final_review":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n16_final_review result is not ok")
    payload = result.payload
    report = QAReport.model_validate(payload.get("qa"))
    if payload.get("visual_reviewed") is not (report.visual_reviewed is True):
        raise QAError("visual_reviewed does not match the report")
    if report.visual_reviewed is not True and "未测" not in report.notes:
        raise QAError("an unreviewed score must say 未测")
    issues = [FilmIssue.model_validate(item) for item in payload.get("issues") or []]
    decisions = [DirectorDecision.model_validate(item) for item in payload.get("decisions") or []]
    flaws = [item for item in issues if item.kind == "hard_flaw"]
    for item in flaws:
        if not item.shot_id:
            raise QAError("a hard flaw needs a shot_id")
    flaw_ids = {item.shot_id for item in flaws}
    decision_ids = []
    regen = 0
    for decision in decisions:
        if decision.target.shot_id not in flaw_ids:
            raise QAError("a decision targets a shot that has no hard flaw")
        decision_ids.append(decision.target.shot_id)
        if decision.action in _REGEN:
            regen += 1
        blob = str(decision.changes)
        if any(word in blob for word in _FORBIDDEN):
            raise QAError("a decision suggests footage or removing the AI label")
        if decision.changes.get("source") != "ai_generated":
            raise QAError("video remediation must stay on AI generation")
    if len(decision_ids) != len(set(decision_ids)):
        raise QAError("a shot has more than one decision")
    if payload.get("budget_taken") != regen:
        raise QAError("budget_taken must equal the number of regenerated shots")
    release = payload.get("release") is True
    disposition = payload.get("disposition")
    if release:
        if disposition != "release" or decisions or flaws:
            raise QAError("a release still has flaws or re-runs")
        brand = payload.get("brand") or {}
        if brand.get("complete") is not True or brand.get("ai_label") is not True:
            raise QAError("a release is missing logo, CTA, or the AI label")
        compliance = payload.get("compliance") or {}
        if compliance.get("passed") is not True:
            raise QAError("a release failed compliance")
        if payload.get("live") is True and report.visual_reviewed is not True:
            raise QAError("live mode cannot release an unreviewed film")
        if payload.get("live") is True:
            if brand.get("logo_pixels") is not True or brand.get("cta_pixels") is not True:
                raise QAError("live release cannot treat an unmeasured logo or CTA as present")
    elif payload.get("live") is True and disposition != "hold":
        raise QAError("live mode must hold when it does not release")
    elif disposition == "redo":
        if not decisions:
            raise QAError("redo needs a decision")
        if set(decision_ids) != flaw_ids:
            raise QAError("redo must cover every hard-flaw shot and no others")
    elif disposition != "hold":
        raise QAError("disposition must be release, redo, or hold")
    return payload
