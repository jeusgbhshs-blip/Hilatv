"""N16 quality check. A blocked review is a failed node, not a deliverable."""

from __future__ import annotations

from workers.nodes.n16_review.schema import NodeResult
from workers.schemas.asset import QAReport


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> dict:
    if result.node != "n16_review":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n16_review result is not ok")
    report = QAReport.model_validate(result.payload.get("qa"))
    stage = result.payload.get("stage")
    if stage not in {"input", "output"}:
        raise QAError("n16_review stage is missing")
    safety = result.payload.get("content_safety")
    if not isinstance(safety, dict) or "passed" not in safety:
        raise QAError("content safety result is missing")
    blocked = bool(result.payload.get("blocked"))
    reasons = list(result.payload.get("block_reasons") or [])
    if blocked != (not result.payload.get("passed")):
        raise QAError("passed and blocked disagree")
    if blocked and not reasons and not report.hard_fail:
        raise QAError("a blocked review needs a reason")
    if not blocked and report.hard_fail:
        raise QAError("a passing review still has hard failures")
    return result.payload
