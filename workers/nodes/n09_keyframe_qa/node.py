"""N9 keyframe review. Pick the highest score, or hand back one director decision."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from workers.logging import log_event
from workers.nodes.n09_keyframe_qa.qa import QAError, check
from workers.nodes.n09_keyframe_qa.schema import N9Input, NodeRequest, NodeResult
from workers.nodes.runtime import Deadline
from workers.qa.director import decide, generator_node
from workers.qa.scores import PASS_TOTAL
from workers.qa.service import review_shot
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.director import DecisionAction, DirectorDecision

NODE = "n09_keyframe_qa"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    payload = N9Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway if gateway is not None else _default_gateway()
    last_error: QAError | None = None
    for try_index in range(1, max_attempts + 1):
        try:
            result = _execute(request, payload, gateway=gateway, timeout_s=timeout_s)
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=try_index,
                error=str(exc),
            )
            continue
        return result
    raise QAError(f"n09_keyframe_qa failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    payload: N9Input,
    *,
    gateway: Any,
    timeout_s: float,
) -> NodeResult:
    deadline = Deadline(timeout_s, node=NODE)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=request.attempt,
        shots=len({row.shot_id for row in payload.candidates}),
    )
    scored: list[tuple[Candidate, QAReport]] = []
    for candidate in payload.candidates:
        if request.shot_id and candidate.shot_id != request.shot_id:
            continue
        deadline.check()
        report = review_shot(
            _review_payload(request, candidate, payload),
            gateway=gateway,
        )
        scored.append((candidate, report))
    if not scored:
        raise QAError("n09 had no candidates for the requested shot")
    updated, decisions = _choose(scored, request=request, gateway=gateway)
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=request.attempt,
        decisions=len(decisions),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "candidates": [row.model_dump(mode="json") for row in updated],
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "shot_ids": sorted({row.shot_id for row in updated}),
        },
        attempt=request.attempt,
    )


def _choose(
    scored: list[tuple[Candidate, QAReport]],
    *,
    request: NodeRequest,
    gateway: Any,
) -> tuple[list[Candidate], list[DirectorDecision]]:
    groups: dict[tuple[str, str], list[tuple[Candidate, QAReport]]] = defaultdict(list)
    for pair in scored:
        frame = str(pair[0].params.get("frame") or "shot")
        groups[(pair[0].shot_id, frame)].append(pair)
    by_shot: dict[str, list[tuple[str, list[tuple[Candidate, QAReport]]]]] = defaultdict(list)
    for (shot_id, frame), pairs in groups.items():
        by_shot[shot_id].append((frame, pairs))
    updated: list[Candidate] = []
    decisions: list[DirectorDecision] = []
    for shot_id, frame_groups in by_shot.items():
        failed = False
        winners: list[tuple[Candidate, QAReport]] = []
        for _frame, pairs in frame_groups:
            best = max(pairs, key=lambda item: item[1].total)
            if best[1].hard_fail or best[1].total < PASS_TOTAL:
                failed = True
            winners.append(best)
        sample = winners[0][0]
        report = min((item[1] for item in winners), key=lambda item: item.total)
        decision = decide(
            report,
            node=generator_node(sample.node),
            shot_id=shot_id,
            attempt=request.attempt,
            model=sample.model,
            prompt=str(sample.params.get("prompt") or ""),
            gateway=gateway,
            project_id=request.project_id,
        )
        if failed and decision.action is DecisionAction.pass_:
            decision = decision.model_copy(
                update={
                    "action": DecisionAction.regenerate,
                    "reason": "有一组关键帧低于 7.5",
                }
            )
        if not failed:
            decision = decision.model_copy(
                update={"action": DecisionAction.pass_, "reason": "质检通过", "changes": {}}
            )
        decisions.append(decision)
        chosen = {
            item[0].candidate_id
            for item in winners
            if decision.action is DecisionAction.pass_ and not item[1].hard_fail
        }
        for _frame, pairs in frame_groups:
            for candidate, report in pairs:
                updated.append(
                    candidate.model_copy(
                        update={
                            "qa": report,
                            "selected": candidate.candidate_id in chosen,
                        }
                    )
                )
    return updated, decisions


def _review_payload(request: NodeRequest, candidate: Candidate, payload: N9Input) -> dict[str, Any]:
    return {
        "project_id": request.project_id,
        "shot_id": candidate.shot_id,
        "node": "n09_keyframe",
        "candidate_uri": candidate.uri,
        "anchor_uri": payload.anchors.get(candidate.shot_id, ""),
        "expected_faces": payload.expected_faces.get(candidate.shot_id, 0),
        "model": candidate.model,
        "purpose": str(candidate.params.get("purpose") or ""),
        "visual": str(candidate.params.get("visual") or ""),
        "voiceover": str(candidate.params.get("voiceover") or ""),
        "shot_size": str(candidate.params.get("shot_size") or ""),
        "shot_type": str(candidate.params.get("camera") or candidate.params.get("shot_type") or ""),
        "generation_mode": str(candidate.params.get("generation_mode") or ""),
        "prompt": str(candidate.params.get("prompt") or ""),
    }


def _default_gateway() -> Any:
    from gateway.service import get_gateway

    return get_gateway()
