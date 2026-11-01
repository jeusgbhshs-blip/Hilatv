"""How many regeneration charges a manual re-run spends.

The only counter is ``open_project_budget``. SPEC.md line 213 gives each shot
its own retries; ``shot_director`` spends one ``try_take`` per regeneration.
A manual re-run reserves that same unit: one per shot each generative node
will actually regenerate. Downstream nodes cover every billable shot.
``shot_id`` limits only the node the user started.
"""

from __future__ import annotations

from typing import Any

from workers.expert.gates import GateError
from workers.qa.budget_store import open_project_budget
from workers.workflow.contract import PIPELINE

GENERATIVE = frozenset({"n06_voiceover", "n08_keyframe", "n10_video"})
_PICTURE = frozenset({"n08_keyframe", "n10_video"})


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


def generation_count(
    start: str,
    shots: list[dict[str, Any]] | None = None,
    shot_id: str | None = None,
) -> int:
    """How many ``try_take`` calls this re-run must be able to pay for.

    ``shots is None`` means the caller has not loaded a script, so each
    generative node counts as one shot. An explicit list counts billable
    shots. Motion-graphics shots do not call the image or video model.
    A voiceover shot with an empty line does not call TTS.
    """

    total = 0
    for name in span(start):
        if name not in GENERATIVE:
            continue
        if shots is None:
            total += 1
            continue
        limit = shot_id if name == start else None
        total += _billable(name, shots, limit)
    return total


def _billable(node: str, shots: list[dict[str, Any]], shot_id: str | None) -> int:
    rows = shots
    if shot_id:
        rows = [item for item in shots if item.get("shot_id") == shot_id]
        if not rows:
            rows = [{"shot_id": shot_id}]
    count = 0
    for shot in rows:
        mode = str(shot.get("generation_mode") or "")
        if node in _PICTURE and mode == "motion_graphics":
            continue
        spoken = str(shot.get("voiceover") or "").strip()
        if node == "n06_voiceover" and "voiceover" in shot and not spoken:
            continue
        count += 1
    return count


def picture_regen_cost(shots: list[dict[str, Any]] | None, shot_id: str) -> int:
    """Keyframe plus video for one shot. Downstream nodes are not included."""

    if shots is None:
        rows = [{"shot_id": shot_id}]
    else:
        rows = [item for item in shots if item.get("shot_id") == shot_id]
        if not rows:
            rows = [{"shot_id": shot_id}]
    return _billable("n08_keyframe", rows, None) + _billable("n10_video", rows, None)


def reserve_picture(
    project_id: str,
    shots: list[dict[str, Any]] | None,
    shot_id: str,
    *,
    operation_id: str | None = None,
) -> int:
    """Charge the shared ledger for one shot's picture only."""

    count = picture_regen_cost(shots, shot_id)
    if count == 0:
        return 0
    budget = open_project_budget(project_id)
    if operation_id:
        key = f"picture:{operation_id}"
        status, token = budget.begin_batch(count, key)
        if status == "already":
            return count
        if status == "refused":
            raise BudgetExhausted(project_id, budget.used, budget.limit)
        if status != "begun":
            raise GateError("这次生成的次数预留尚未确认，请保留 operation_id", status=409)
        if budget.finish_batch(count, key, token) not in {"taken", "already", "audited"}:
            raise GateError("这次生成的次数结算尚未确认，请保留 operation_id", status=409)
        return count
    if not budget.try_take_n(count):
        raise BudgetExhausted(project_id, budget.used, budget.limit)
    return count


def reserve(
    project_id: str,
    start: str,
    *,
    shots: list[dict[str, Any]] | None = None,
    shot_id: str | None = None,
) -> int:
    """Charge the shared ledger before a manual re-run starts.

    A span with no image, video, or voiceover generation charges nothing.
    When the remaining count cannot cover every shot in the span, nothing
    is taken.
    """

    count = generation_count(start, shots, shot_id)
    if count == 0:
        return 0
    budget = open_project_budget(project_id)
    if not budget.try_take_n(count):
        raise BudgetExhausted(project_id, budget.used, budget.limit)
    return count
