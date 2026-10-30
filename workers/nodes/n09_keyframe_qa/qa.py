"""N9 checks the decision and the selected keyframe, not the pixels again."""

from __future__ import annotations

from collections import defaultdict

from workers.nodes.n09_keyframe_qa.schema import NodeResult
from workers.qa.scores import PASS_TOTAL
from workers.schemas.asset import Candidate
from workers.schemas.director import DecisionAction, DirectorDecision


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> list[Candidate]:
    if result.node != "n09_keyframe_qa":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n09_keyframe_qa result is not ok")
    rows = [_candidate(item) for item in result.payload.get("candidates") or []]
    if not rows:
        raise QAError("n09 returned no candidates")
    decisions = _decisions(result.payload.get("decisions") or [])
    by_shot: dict[str, list[DirectorDecision]] = defaultdict(list)
    for decision in decisions:
        if decision.target.shot_id:
            by_shot[decision.target.shot_id].append(decision)
    groups: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for row in rows:
        groups[(row.shot_id, str(row.params.get("frame") or "shot"))].append(row)
    shots = {row.shot_id for row in rows}
    if set(by_shot) != shots:
        raise QAError("each shot needs one director decision")
    for shot_id in shots:
        if len(by_shot[shot_id]) != 1:
            raise QAError(f"{shot_id} has more than one decision")
        decision = by_shot[shot_id][0]
        _check_decision(decision)
        for (group_shot, _frame), group in groups.items():
            if group_shot != shot_id:
                continue
            _check_group(group, decision)
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


def _check_decision(decision: DirectorDecision) -> None:
    if not decision.target.node:
        raise QAError("decision is missing a target node")
    if decision.max_attempts_left < 0 or decision.max_attempts_left > 3:
        raise QAError("max_attempts_left is outside 0..3")


def _check_group(rows: list[Candidate], decision: DirectorDecision) -> None:
    selected = [row for row in rows if row.selected]
    if decision.action is DecisionAction.pass_:
        if len(selected) != 1:
            raise QAError(f"{rows[0].shot_id} pass must select one candidate in each group")
        report = selected[0].qa
        if report.hard_fail or report.total < PASS_TOTAL:
            raise QAError(f"{selected[0].candidate_id} was selected below the pass line")
        return
    if selected:
        raise QAError(f"{rows[0].shot_id} kept a selection after {decision.action.value}")
