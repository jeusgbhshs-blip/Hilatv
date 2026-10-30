"""N16 compliance review. Content safety goes through the gateway.

Input and output are separate calls so the gateway log shows both stages.
A failing review, an extreme-word hit, or a bad licence blocks delivery.
Medical, food, and finance copy is flagged for a person and does not, by
itself, delete the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers.compliance.consent_gate import assert_generation_allowed, assert_voice_allowed
from workers.compliance.copy import bundle_text, extreme_hits
from workers.compliance.sectors import manual_sectors
from workers.logging import log_event
from workers.nodes.n16_review.qa import QAError, check
from workers.nodes.n16_review.schema import N16Input, NodeRequest, NodeResult
from workers.nodes.runtime import Deadline
from workers.schemas.asset import QAReport, QAScores
from workers.schemas.label_lock import LabelLocked, walk_label_edits
from workers.schemas.licensing import block_reason, today_shanghai
from workers.workflow.store import project_path

NODE = "n16_review"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 2,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N16Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    deadline = Deadline(timeout_s, node=NODE)
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, attempt=attempt, gateway=gateway)
            check(result)
        except QAError as exc:
            if not exc.retryable:
                raise
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            continue
        return result
    message = f"n16_review failed after {max_attempts} attempts: {last_error}"
    raise QAError(message) from last_error


def _execute(request: NodeRequest, *, attempt: int, gateway: Any) -> NodeResult:
    payload = N16Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        stage=payload.stage,
    )
    try:
        walk_label_edits(request.payload)
        if payload.instruction:
            walk_label_edits(payload.instruction)
    except LabelLocked as exc:
        raise QAError(str(exc)) from exc
    if payload.script is not None:
        for shot in payload.script.shots:
            try:
                assert_generation_allowed(shot, payload.brand_kit, archived=payload.brand_archived)
            except ValueError as exc:
                raise QAError(str(exc)) from exc
    voice = payload.brand_kit.voice.tts_voice if payload.brand_kit is not None else None
    try:
        assert_voice_allowed(voice, payload.brand_kit, archived=payload.brand_archived)
    except ValueError as exc:
        raise QAError(str(exc)) from exc
    root = project_path(request.project_id, create=True).resolve()
    for raw_path in payload.media_paths:
        _contained(root, raw_path)
    text = bundle_text(payload.brief, payload.script, list(payload.texts))
    extremes = extreme_hits(text, payload.brand_kit)
    sectors = manual_sectors(text, payload.brand_kit)
    safety = gateway.content_safety(
        text,
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        params={"stage": payload.stage},
    )
    if not isinstance(safety, dict) or "passed" not in safety:
        raise QAError("content safety returned no decision", retryable=True)
    reasons: list[str] = []
    if safety.get("passed") is not True:
        detail = str(safety.get("reason") or "content safety rejected the text")
        reasons.append(detail)
    if extremes:
        reasons.append("extreme words: " + "、".join(extremes))
    if payload.licensing is not None:
        licence = block_reason(list(payload.licensing.records), today=today_shanghai())
        if licence:
            reasons.append(licence)
    passed = not reasons
    report = _report(passed, reasons, manual=bool(sectors))
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        stage=payload.stage,
        passed=passed,
        manual_review=bool(sectors),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=attempt,
        payload={
            "stage": payload.stage,
            "passed": passed,
            "blocked": not passed,
            "block_reasons": reasons,
            "manual_review": bool(sectors),
            "manual_review_sectors": sectors,
            "extreme_words": extremes,
            "content_safety": safety,
            "licensing": (payload.licensing.model_dump(mode="json") if payload.licensing else None),
            "qa": report.model_dump(mode="json"),
        },
    )


def _report(passed: bool, reasons: list[str], *, manual: bool) -> QAReport:
    score = 8 if passed else 2
    note = "待人工审核" if manual else "合规审查"
    if reasons:
        note = "; ".join(reasons)
    return QAReport(
        scores=QAScores(
            product_fidelity=score,
            motion_quality=score,
            aesthetics=score,
            prompt_match=score,
            artifact_free=score,
        ),
        hard_fail=reasons,
        total=float(score),
        evaluator="n16-compliance",
        notes=note,
        visual_reviewed=False,
    )


def _contained(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise QAError("media path must stay inside the project directory")
    return resolved


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
