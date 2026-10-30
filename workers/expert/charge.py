"""How many regeneration charges a manual re-run spends.

The only counter is ``open_project_budget``. Each generative node in the span
(this node and everything after it) spends one via ``try_take``.
"""

from __future__ import annotations

from workers.qa.budget_store import open_project_budget
from workers.workflow.contract import PIPELINE

GENERATIVE = frozenset({"n06_voiceover", "n08_keyframe", "n10_video"})


class BudgetExhausted(RuntimeError):
    """The project ledger cannot cover this re-run. The count is not lowered."""

    def __init__(self, project_id: str, used: int, limit: int) -> None:
        self.project_id = project_id
        self.used = used
        self.limit = limit
        super().__init__(f"项目重生次数已用完（已用 {used} / 上限 {limit}），不能再重跑生成节点")


def span(start: str) -> list[str]:
    if start not in PIPELINE:
        raise ValueError(f"unknown node {start}")
    return list(PIPELINE[PIPELINE.index(start) :])


def generation_count(start: str) -> int:
    return sum(1 for name in span(start) if name in GENERATIVE)


def reserve(project_id: str, start: str) -> int:
    """Charge the shared ledger before a manual re-run starts.

    A span with no image, video, or voiceover generation charges nothing.
    When the remaining count cannot cover the span, nothing is taken.
    """

    count = generation_count(start)
    if count == 0:
        return 0
    budget = open_project_budget(project_id)
    budget.allow()
    if budget.used + count > budget.limit:
        raise BudgetExhausted(project_id, budget.used, budget.limit)
    taken = 0
    while taken < count:
        if not budget.try_take():
            raise BudgetExhausted(project_id, budget.used, budget.limit)
        taken += 1
    return taken
