"""N5 storyboard. One Script in, the same Script with shots filled in.

Camera hints come from the gateway. The mock hint is empty, so the shot library
and the N5 mode rules decide the board. The same input replans the same shots.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from workers.logging import log_event
from workers.nodes.n05_storyboard.plan import PlanError, is_promo, plan_shots, shot_bounds
from workers.nodes.n05_storyboard.presets import load_presets
from workers.nodes.n05_storyboard.prompts import NO_DRAWN_TEXT, render_storyboard, system_prompt
from workers.nodes.n05_storyboard.qa import QAError, check
from workers.nodes.n05_storyboard.schema import N5Input, NodeRequest, NodeResult, StoryboardHint

NODE = "n05_storyboard"


class Deadline:
    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n05_storyboard exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n05_storyboard exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N5Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    feedback = ""
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(
                request,
                attempt=attempt,
                timeout_s=timeout_s,
                gateway=gateway,
                feedback=feedback,
            )
            check(result)
        except QAError as exc:
            last_error = exc
            feedback = str(exc)
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
    raise QAError(f"n05_storyboard failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
    feedback: str,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N5Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    presets = load_presets()
    _min, _max, lo, hi = shot_bounds(payload.brief.duration_s, promo=is_promo(payload.brief))
    prompt = render_storyboard(
        script=payload.script,
        presets=presets,
        duration_s=payload.brief.duration_s,
        min_s=lo,
        max_s=hi,
        feedback=feedback,
    )
    if NO_DRAWN_TEXT not in prompt:
        raise QAError("storyboard prompt is missing the no-text constraint")
    deadline.check()
    hint = _hint(
        gateway,
        prompt,
        project_id=request.project_id,
        shot_id=request.shot_id,
        attempt=attempt,
        language=payload.script.language,
        deadline=deadline,
    )
    try:
        script = plan_shots(payload.script, payload.brief, payload.brand_kit, hints=hint)
    except (PlanError, ValidationError) as exc:
        raise QAError(f"storyboard failed: {exc}") from exc
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        shots=len(script.shots),
        duration_s=payload.brief.duration_s,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "script": script.model_dump(mode="json"),
            "shots": [shot.model_dump(mode="json") for shot in script.shots],
            "brief": payload.brief.model_dump(mode="json"),
            "brand_kit": (payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None),
            "prompt": prompt,
        },
        attempt=attempt,
    )


def _hint(
    gateway: Any,
    prompt: str,
    *,
    project_id: str,
    shot_id: str | None,
    attempt: int,
    language: str,
    deadline: Deadline,
) -> StoryboardHint:
    deadline.check()
    try:
        raw = gateway.generate_text(
            prompt,
            schema=StoryboardHint,
            system=system_prompt(),
            seed=0,
            language=language,
            project_id=project_id,
            node=NODE,
            shot_id=shot_id,
            attempt=attempt,
        )
        parsed = StoryboardHint.model_validate(raw)
    except TimeoutError:
        raise
    except Exception as exc:
        log_event(
            "node_llm_failed",
            project_id=project_id,
            node=NODE,
            shot_id=shot_id,
            attempt=attempt,
            error=str(exc)[:300],
        )
        parsed = StoryboardHint()
    deadline.check()
    return parsed


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
