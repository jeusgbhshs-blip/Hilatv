"""N18 dialogue edit. One sentence in, a chapter 5 change set out.

This node does not render media. The revision runner reruns the nodes named
in the plan and reuses cached shots for the rest.
"""

from __future__ import annotations

from typing import Any

from workers.logging import log_event
from workers.nodes.n18_revision.apply import apply_brand, apply_script
from workers.nodes.n18_revision.brand_use import gate_brand
from workers.nodes.n18_revision.deps import plan_for
from workers.nodes.n18_revision.parse import parse_edit
from workers.nodes.n18_revision.qa import QAError, check
from workers.nodes.n18_revision.schema import N18Input, NodeRequest, NodeResult
from workers.nodes.runtime import Deadline

NODE = "n18_revision"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 30.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N18Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway if gateway is not None else _default_gateway()
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(request, attempt=attempt, timeout_s=timeout_s, gateway=gateway)
            result = result.model_copy(update={"attempt": attempt})
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            if not exc.retryable:
                raise
            continue
        return result
    raise QAError(f"n18_revision failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
) -> NodeResult:
    deadline = Deadline(timeout_s, node=NODE)
    payload = N18Input.model_validate(request.payload)
    focused = request.shot_id or payload.focused_shot_id
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=focused,
        attempt=attempt,
    )
    deadline.check()
    brand = gate_brand(payload.brand_kit, from_archive=False)
    parsed = parse_edit(
        payload.script,
        payload.instruction,
        focused_shot_id=focused,
        gateway=gateway,
        project_id=request.project_id,
        attempt=attempt,
    )
    if parsed.status != "apply" or parsed.directive is None:
        log_event(
            "revision_not_applied",
            project_id=request.project_id,
            node=NODE,
            shot_id=focused,
            attempt=attempt,
            status=parsed.status,
        )
        return NodeResult(
            project_id=request.project_id,
            node=NODE,
            ok=True,
            payload={
                "status": parsed.status,
                "question": parsed.question,
                "notice": parsed.notice,
                "script": payload.script.model_dump(mode="json"),
                "brand_kit": brand.model_dump(mode="json") if brand is not None else None,
                "nodes": [],
                "video_shots": [],
                "reuse_shots": [],
            },
            attempt=request.attempt,
        )
    directive = parsed.directive
    script = apply_script(payload.script, directive)
    brand = apply_brand(brand, directive)
    plan = plan_for(script, directive)
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=focused,
        attempt=attempt,
        targets=len(directive.targets),
        video_shots=len(plan.video_shots),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "status": "apply",
            "question": "",
            "notice": parsed.notice,
            "directive": directive.model_dump(mode="json"),
            "script": script.model_dump(mode="json"),
            "brand_kit": brand.model_dump(mode="json") if brand is not None else None,
            "nodes": plan.nodes,
            "video_shots": plan.video_shots,
            "reuse_shots": plan.reuse_shots,
        },
        attempt=request.attempt,
    )


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
