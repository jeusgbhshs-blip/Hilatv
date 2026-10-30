"""How many regeneration charges a manual re-run spends.

The count is the number of generative nodes in the span (this node and
everything after it). The only counter is ``open_project_budget``.
"""

from __future__ import annotations

from workers.qa.budget_store import BudgetExhausted, open_project_budget
from workers.workflow.contract import PIPELINE

GENERATIVE = frozenset({"n06_voiceover", "n08_keyframe", "n10_video"})


def span(start: str) -> list[str]:
    if start not in PIPELINE:
        raise ValueError(f"unknown node {start}")
    return list(PIPELINE[PIPELINE.index(start) :])


def generation_count(start: str) -> int:
    return sum(1 for name in span(start) if name in GENERATIVE)


def reserve(project_id: str, start: str) -> int:
    """Charge the project ledger before a manual re-run starts.

    A span with no image, video, or voiceover generation charges nothing.
    When the remaining count cannot cover the span, the re-run is refused
    and the ledger is left unchanged.
    """

    count = generation_count(start)
    if count == 0:
        return 0
    budget = open_project_budget(project_id)
    if budget.remaining < count:
        raise BudgetExhausted(project_id, budget.used, budget.limit)
    budget.charge(count)
    return count
