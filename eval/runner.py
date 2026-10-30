"""Run benchmark sentences on the T10 line.

Mock mode calls the same nodes the film activities call, through N5, and does
not encode an MP4. Live mode calls ``run_and_wait`` (Temporal, N1 through N15).
Scoring always goes through the T12 review port.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from eval.cases import Case, project_id_for
from eval.scoring import CaseScore, ShotScore, score_state


@dataclass
class CaseOutcome:
    case_id: str
    industry: str
    status: str
    score: float | None
    hard_shots: int
    shot_count: int
    elapsed_s: float
    cost_cny: str
    error: str = ""
    deliverable: str | None = None
    reviewed_shots: int = 0
    unreviewed_shots: int = 0
    text_only_shots: int = 0
    invalid_shots: int = 0
    shots: list[ShotScore] = field(default_factory=list)


def run_case(case: Case, *, mode: str, gateway: Any) -> CaseOutcome:
    project_id = project_id_for(case.case_id)
    started = time.perf_counter()
    try:
        if mode == "live":
            state, deliverable = _run_film(case, project_id)
        elif mode == "mock":
            state, deliverable = _run_storyboard(case, project_id, gateway)
        else:
            raise ValueError(f"unknown mode {mode}")
        scored = score_state(state, project_id=project_id, gateway=gateway)
    except Exception as exc:
        return _failed(case, project_id, gateway, started, exc)
    return _ok(case, project_id, gateway, started, scored, deliverable)


def _ok(
    case: Case,
    project_id: str,
    gateway: Any,
    started: float,
    scored: CaseScore,
    deliverable: object,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case.case_id,
        industry=case.industry,
        status="ok",
        score=scored.score,
        hard_shots=scored.hard_shots,
        shot_count=scored.shot_count,
        elapsed_s=round(time.perf_counter() - started, 3),
        cost_cny=_cost(gateway, project_id),
        deliverable=str(deliverable) if deliverable else None,
        reviewed_shots=scored.reviewed_shots,
        unreviewed_shots=scored.unreviewed_shots,
        text_only_shots=scored.text_only_shots,
        invalid_shots=scored.invalid_shots,
        shots=scored.shots,
    )


def _failed(
    case: Case,
    project_id: str,
    gateway: Any,
    started: float,
    exc: Exception,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case.case_id,
        industry=case.industry,
        status="error",
        score=None,
        hard_shots=0,
        shot_count=0,
        elapsed_s=round(time.perf_counter() - started, 3),
        cost_cny=_cost(gateway, project_id),
        error=f"{type(exc).__name__}: {exc}"[:500],
    )


def _run_storyboard(
    case: Case,
    project_id: str,
    gateway: Any,
) -> tuple[dict[str, Any], None]:
    from workers.nodes.n01_brief.node import run as run_brief
    from workers.nodes.n04_script.node import run as run_script
    from workers.nodes.n05_storyboard.node import run as run_board
    from workers.workflow.brand import resolve_brand_kit
    from workers.workflow.concept import choose_direction

    brief_result = run_brief(
        {
            "project_id": project_id,
            "payload": {
                "raw_input": case.sentence,
                "attachments": [],
                "brand_kit": None,
            },
            "attempt": 1,
        },
        timeout_s=90,
        max_attempts=3,
        gateway=gateway,
    )
    brief = brief_result.payload["brief"]
    kit = resolve_brand_kit(inline=None, brand_id=None, project_id=project_id, attempt=1)
    concept = choose_direction(brief)
    script_result = run_script(
        {
            "project_id": project_id,
            "payload": {"brief": brief, "brand_kit": kit},
            "attempt": 1,
        },
        timeout_s=120,
        max_attempts=3,
        gateway=gateway,
    )
    script = script_result.payload["script"]
    brief = script_result.payload.get("brief") or brief
    board = run_board(
        {
            "project_id": project_id,
            "payload": {"brief": brief, "script": script, "brand_kit": kit},
            "attempt": 1,
        },
        timeout_s=90,
        max_attempts=3,
        gateway=gateway,
    )
    state = {
        "brief": board.payload.get("brief") or brief,
        "script": board.payload["script"],
        "concept": concept,
        "brand_kit": kit,
    }
    return state, None


def _run_film(case: Case, project_id: str) -> tuple[dict[str, Any], object]:
    from workers.workflow.service import run_and_wait
    from workers.workflow.store import load_checkpoint

    result = asyncio.run(
        run_and_wait(
            project_id=project_id,
            sentence=case.sentence,
            keyframe_candidates=3,
            video_candidates=3,
        )
    )
    state = load_checkpoint(project_id)
    deliverable = result.get("deliverable")
    state["deliverable"] = deliverable
    return state, deliverable


def _cost(gateway: Any, project_id: str) -> str:
    try:
        rows = gateway.store.list_logs(project_id=project_id)
    except Exception:
        return "0"
    total = Decimal("0")
    for row in rows:
        total += Decimal(str(row.get("cost_cny") or "0"))
    return format(total, "f")
