"""N1 demand understanding. One sentence in, a chapter 5 Brief out.

Run again with the same JSON to rebuild the same Brief. Model calls go through
the gateway; with no key the mock extraction is empty and the industry table fills
the gaps.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from workers.logging import log_event
from workers.nodes.n01_brief.assemble import assemble
from workers.nodes.n01_brief.attachments import Deadline, parse_attachment
from workers.nodes.n01_brief.prompts import render_extract, summarize_brand, system_prompt
from workers.nodes.n01_brief.qa import QAError, check
from workers.nodes.n01_brief.schema import ExtractedBrief, N1Input, NodeRequest, NodeResult
from workers.nodes.n01_brief.signals import parse_text

NODE = "n01_brief"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N1Input.model_validate(request.payload)
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
    raise QAError(f"n01_brief failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
    feedback: str,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N1Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    parsed_attachments = [
        parse_attachment(
            item,
            deadline=deadline,
            gateway=gateway,
            project_id=request.project_id,
            shot_id=request.shot_id,
            attempt=attempt,
        )
        for item in payload.attachments
    ]
    summary = _attachment_summary(parsed_attachments)
    prompt = render_extract(
        raw_input=payload.raw_input,
        attachment_summary=summary,
        brand_summary=summarize_brand(payload.brand_kit),
        feedback=feedback,
    )
    deadline.check()
    extracted = _extract(
        gateway,
        prompt,
        project_id=request.project_id,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    deadline.check()
    try:
        brief = assemble(
            project_id=request.project_id,
            raw_input=payload.raw_input,
            parsed=parse_text(payload.raw_input),
            attachments=parsed_attachments,
            brand=payload.brand_kit,
            extracted=extracted,
        )
    except ValidationError as exc:
        raise QAError(f"brief failed validation: {exc}") from exc
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        duration_s=brief.duration_s,
        questions=len(brief.open_questions),
        video_type=brief.video_type,
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "brief": brief.model_dump(mode="json"),
            "attachments": [item.as_dict() for item in parsed_attachments],
            "prompt": prompt,
        },
        attempt=attempt,
    )


def _extract(
    gateway: Any,
    prompt: str,
    *,
    project_id: str,
    shot_id: str | None,
    attempt: int,
) -> ExtractedBrief:
    try:
        raw = gateway.generate_text(
            prompt,
            schema=ExtractedBrief,
            system=system_prompt(),
            seed=0,
            project_id=project_id,
            node=NODE,
            shot_id=shot_id,
            attempt=attempt,
        )
        return ExtractedBrief.model_validate(raw)
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
        return ExtractedBrief()


def _attachment_summary(items: list[Any]) -> str:
    if not items:
        return "无"
    blocks: list[str] = []
    for item in items:
        if item.error:
            blocks.append(f"[{item.kind}] {item.uri} 失败：{item.error}")
            continue
        text = item.text.strip().replace("\n", " ")
        if len(text) > 1500:
            text = text[:1500] + "…"
        blocks.append(f"[{item.kind}] {item.filename or item.uri}\n{text}")
    joined = "\n".join(blocks)
    if len(joined) > 6000:
        return joined[:6000] + "…"
    return joined


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
