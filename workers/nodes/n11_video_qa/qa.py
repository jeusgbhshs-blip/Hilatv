"""N11 checks the decision, the selected clip, and any splice plan."""

from __future__ import annotations

from collections import defaultdict

from workers.nodes.n11_video_qa.schema import NodeResult
from workers.qa.scores import PASS_TOTAL
from workers.schemas.asset import Candidate
from workers.schemas.director import DecisionAction, DirectorDecision


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> list[Candidate]:
    if result.node != "n11_video_qa":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n11_video_qa result is not ok")
    rows = [_candidate(item) for item in result.payload.get("candidates") or []]
    if not rows:
        raise QAError("n11 returned no candidates")
    decisions = _decisions(result.payload.get("decisions") or [])
    by_shot: dict[str, list[DirectorDecision]] = defaultdict(list)
    for decision in decisions:
        if decision.target.shot_id:
            by_shot[decision.target.shot_id].append(decision)
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        groups[row.shot_id].append(row)
    if set(by_shot) != set(groups):
        raise QAError("each shot needs one director decision")
    for shot_id, group in groups.items():
        if len(by_shot[shot_id]) != 1:
            raise QAError(f"{shot_id} has more than one decision")
        decision = by_shot[shot_id][0]
        if decision.max_attempts_left < 0 or decision.max_attempts_left > 3:
            raise QAError("max_attempts_left is outside 0..3")
        selected = [row for row in group if row.selected]
        if decision.action is DecisionAction.pass_:
            if len(selected) != 1:
                raise QAError(f"{shot_id} pass must select one clip")
            report = selected[0].qa
            if report.hard_fail or report.total < PASS_TOTAL:
                raise QAError(f"{selected[0].candidate_id} was selected below the pass line")
        elif selected:
            raise QAError(f"{shot_id} kept a selection after {decision.action.value}")
    return rows


def _candidate(raw: object) -> Candidate:
    try:
        return Candidate.model_validate(raw)
    except Exception as exc:
        raise QAError(f"candidate is not a chapter 5 Candidate: {exc}") from exc


def _decisions(raw: object) -> list[DirectorDecision]:
    if not isinstance(raw, list):
        raise QAError("decisions must be a list")
    found: list[DirectorDecision] = []
    for item in raw:
        try:
            found.append(DirectorDecision.model_validate(item))
        except Exception as exc:
            raise QAError(f"decision is not a DirectorDecision: {exc}") from exc
    return found
