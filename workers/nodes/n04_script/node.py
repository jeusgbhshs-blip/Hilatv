"""N4 script. One Brief in, a chapter 5 Script out.

The Chinese master is written first. Other languages are localized from the same
facts, not translated line by line. With no key the mock draft is empty and the
rule writer fills a script that stays inside the length window.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from workers.logging import log_event
from workers.nodes.n04_script.compose import ComposeError, compose_script, script_id_for
from workers.nodes.n04_script.facts import collect_facts
from workers.nodes.n04_script.prompts import (
    NO_DRAWN_TEXT,
    render_draft,
    render_localize,
    render_review,
    system_prompt,
)
from workers.nodes.n04_script.qa import QAError, check
from workers.nodes.n04_script.schema import (
    N4Input,
    NodeRequest,
    NodeResult,
    ScriptDraft,
    ScriptReview,
)
from workers.qa.copycheck import hook_unit_limit, language_family, target_units
from workers.schemas.brief import Brief
from workers.schemas.script import Script

NODE = "n04_script"


class Deadline:
    """Node-level timeout. Model calls check it before and after."""

    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n04_script exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n04_script exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N4Input.model_validate(request.payload)
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
    raise QAError(f"n04_script failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
    feedback: str,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N4Input.model_validate(request.payload)
    brief = payload.brief
    duration = brief.duration_s if payload.story_duration_s is None else payload.story_duration_s
    if duration > brief.duration_s:
        raise QAError("story duration cannot exceed the requested whole film")
    facts = collect_facts(brief, payload.brand_kit)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    draft_prompt = render_draft(
        brief=brief,
        facts=facts,
        hook_units=hook_unit_limit("zh"),
        target=int(round(target_units(duration, "zh"))),
        feedback=feedback,
        duration_s=duration,
    )
    if NO_DRAWN_TEXT not in draft_prompt:
        raise QAError("script prompt is missing the no-text constraint")
    deadline.check()
    zh_draft = _complete(
        gateway,
        draft_prompt,
        ScriptDraft,
        project_id=request.project_id,
        shot_id=request.shot_id,
        attempt=attempt,
        language="zh",
        deadline=deadline,
    )
    try:
        master = compose_script(
            project_id=request.project_id,
            brief=brief,
            facts=facts,
            language="zh",
            draft=zh_draft,
            duration_s=duration,
        )
    except (ComposeError, ValidationError) as exc:
        raise QAError(f"chinese master failed: {exc}") from exc
    prompts = [draft_prompt]
    variants: list[Script] = []
    for language in brief.languages:
        if language_family(language) == "zh":
            script = master
            if language != "zh":
                script = _retag(master, request.project_id, brief, language)
            variants.append(script)
            continue
        local_prompt = render_localize(
            brief=brief,
            facts=facts,
            language=language,
            master=master,
            target=int(round(target_units(duration, language))),
            feedback=feedback,
            duration_s=duration,
        )
        prompts.append(local_prompt)
        deadline.check()
        local_draft = _complete(
            gateway,
            local_prompt,
            ScriptDraft,
            project_id=request.project_id,
            shot_id=request.shot_id,
            attempt=attempt,
            language=language,
            deadline=deadline,
        )
        try:
            variants.append(
                compose_script(
                    project_id=request.project_id,
                    brief=brief,
                    facts=facts,
                    language=language,
                    draft=local_draft,
                    duration_s=duration,
                )
            )
        except (ComposeError, ValidationError) as exc:
            raise QAError(f"{language} script failed: {exc}") from exc
    primary = variants[0]
    review_prompt = render_review(script=primary, facts=facts, feedback=feedback)
    prompts.append(review_prompt)
    deadline.check()
    review = _complete(
        gateway,
        review_prompt,
        ScriptReview,
        project_id=request.project_id,
        shot_id=request.shot_id,
        attempt=attempt,
        language=primary.language,
        deadline=deadline,
    )
    if not (
        review.passes
        and review.hook_in_first_3s
        and review.selling_points_from_brand
        and review.numbers_sourced
    ):
        raise QAError(review.notes or "script self-review failed")
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        language=primary.language,
        sections=len(primary.sections),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "story_duration_s": payload.story_duration_s,
            "script": primary.model_dump(mode="json"),
            "master": master.model_dump(mode="json"),
            "variants": [item.model_dump(mode="json") for item in variants],
            "brief": brief.model_dump(mode="json"),
            "brand_kit": (payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None),
            "prompt": draft_prompt,
            "prompts": prompts,
            "review": review.model_dump(mode="json"),
        },
        attempt=attempt,
    )


def _retag(master: Script, project_id: str, brief: Brief, language: str) -> Script:
    return master.model_copy(
        update={
            "script_id": script_id_for(project_id, brief.brief_id, language),
            "language": language,
        }
    )


def _complete(
    gateway: Any,
    prompt: str,
    schema: type[ScriptDraft] | type[ScriptReview],
    *,
    project_id: str,
    shot_id: str | None,
    attempt: int,
    language: str,
    deadline: Deadline,
) -> ScriptDraft | ScriptReview:
    deadline.check()
    try:
        raw = gateway.generate_text(
            prompt,
            schema=schema,
            system=system_prompt(),
            seed=0,
            language=language,
            project_id=project_id,
            node=NODE,
            shot_id=shot_id,
            attempt=attempt,
        )
        parsed = schema.model_validate(raw)
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
        parsed = schema()
    deadline.check()
    return parsed


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
