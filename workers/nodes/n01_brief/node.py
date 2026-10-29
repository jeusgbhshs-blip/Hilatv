"""N1 skeleton: validate, time out, retry, check, log, and rerun.

The real brief parser is T05. This module only proves the node contract.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from workers.logging import log_event
from workers.nodes.n01_brief.qa import QAError, check
from workers.nodes.n01_brief.schema import NodeRequest, NodeResult

PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
)


def render_prompt(project_id: str) -> str:
    return _ENV.get_template("stub.j2").render(project_id=project_id)


def _execute(request: NodeRequest, *, attempt: int, timeout_s: float) -> NodeResult:
    if timeout_s <= 0:
        raise TimeoutError("n01_brief exceeded timeout")
    started = time.monotonic()
    prompt = render_prompt(request.project_id)
    if time.monotonic() - started > timeout_s:
        raise TimeoutError("n01_brief exceeded timeout")
    log_event(
        "node_finished",
        project_id=request.project_id,
        node="n01_brief",
        shot_id=request.shot_id,
        attempt=attempt,
    )
    return NodeResult(
        project_id=request.project_id,
        node="n01_brief",
        ok=True,
        payload={"status": "stub", "task": "T05", "prompt": prompt},
        attempt=attempt,
    )


def run(raw: dict[str, Any], *, timeout_s: float = 30.0, max_attempts: int = 3) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(request, attempt=attempt, timeout_s=timeout_s)
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node="n01_brief",
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            continue
        return result
    raise QAError(f"n01_brief failed after {max_attempts} attempts") from last_error
