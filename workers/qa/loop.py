"""Apply one decision at a time, at most three reviews per shot.

This is the executor a workflow runs. It does not sit inside the T10 film
pipeline: that line still skips N9 and N11.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from workers.qa.director import decide
from workers.qa.scores import is_quality_pass
from workers.qa.settings import RetryBudget
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.director import DecisionAction, DirectorDecision


@dataclass
class LoopResult:
    decisions: list[DirectorDecision]
    candidates: list[Candidate]
    attempts: int


def run_shot_loop(
    candidates: list[Candidate],
    *,
    shot_id: str,
    generator_node: str,
    review: Callable[[list[Candidate]], list[QAReport]],
    apply: Callable[[DirectorDecision], list[Candidate]] | None = None,
    project_id: str | None = None,
    gateway: Any | None = None,
    budget: RetryBudget | None = None,
) -> LoopResult:
    if not candidates:
        raise ValueError("a shot needs at least one candidate")
    budget = budget if budget is not None else RetryBudget()
    current = list(candidates)
    decisions: list[DirectorDecision] = []
    for attempt in range(1, 4):
        reports = review(current)
        if len(reports) != len(current):
            raise ValueError("review must score every candidate")
        best = max(reports, key=lambda item: item.total)
        sample = current[reports.index(best)]
        decision = decide(
            best,
            node=generator_node,
            shot_id=shot_id,
            attempt=attempt,
            model=sample.model,
            prompt=str(sample.params.get("prompt") or ""),
            gateway=gateway,
            project_id=project_id,
            budget=budget,
        )
        decisions.append(decision)
        current = _mark(current, reports, decision)
        if decision.action in {
            DecisionAction.pass_,
            DecisionAction.fallback,
            DecisionAction.ask_user,
        }:
            return LoopResult(decisions=decisions, candidates=current, attempts=attempt)
        if apply is None:
            raise RuntimeError("regenerate requested without an apply callback")
        current = list(apply(decision))
        if not current:
            raise RuntimeError("apply returned no candidates")
    raise RuntimeError("shot exceeded 3 reviews")


def _mark(
    candidates: list[Candidate],
    reports: list[QAReport],
    decision: DirectorDecision,
) -> list[Candidate]:
    chosen: str | None = None
    if decision.action is DecisionAction.pass_:
        eligible = [
            pair for pair in zip(candidates, reports, strict=True) if is_quality_pass(pair[1])
        ]
        if eligible:
            winner = max(eligible, key=lambda pair: pair[1].total)
            chosen = winner[0].candidate_id
    marked: list[Candidate] = []
    for candidate, report in zip(candidates, reports, strict=True):
        marked.append(
            candidate.model_copy(
                update={"qa": report, "selected": candidate.candidate_id == chosen}
            )
        )
    return marked
