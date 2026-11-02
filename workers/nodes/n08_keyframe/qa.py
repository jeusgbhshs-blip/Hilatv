"""Quality check for N8. Full visual scoring waits for N9 (T12)."""

from __future__ import annotations

from gateway.constants import NO_RENDERED_TEXT
from workers.nodes.n08_keyframe.schema import NodeResult
from workers.nodes.shot_meta import needs_end_frame
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode, Script, Shot

MIN_CANDIDATES = 3


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> list[Candidate]:
    if result.node != "n08_keyframe":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n08_keyframe result is not ok")
    script = Script.model_validate(result.payload.get("script"))
    wanted = set(result.payload.get("shot_ids") or [])
    if not wanted:
        raise QAError("n08_keyframe names no shots")
    rows = [_candidate(item) for item in result.payload.get("candidates") or []]
    by_shot: dict[str, list[Candidate]] = {}
    for row in rows:
        by_shot.setdefault(row.shot_id, []).append(row)
    shots = {shot.shot_id: shot for shot in script.shots}
    for shot_id in wanted:
        shot = shots.get(shot_id)
        if shot is None:
            raise QAError(f"unknown shot {shot_id}")
        _audit_shot(shot, by_shot.get(shot_id, []))
    return rows


def _candidate(raw: object) -> Candidate:
    try:
        return Candidate.model_validate(raw)
    except Exception as exc:
        raise QAError(f"candidate is not a chapter 5 Candidate: {exc}") from exc


def _audit_shot(shot: Shot, rows: list[Candidate]) -> None:
    from workers.compliance.moderation import internal_skip_visual_review

    internal = internal_skip_visual_review()
    if shot.generation_mode is GenerationMode.motion_graphics:
        if rows:
            raise QAError(f"{shot.shot_id} is motion graphics and must not call an image model")
        return
    first = [row for row in rows if row.params.get("frame") == "first"]
    last = [row for row in rows if row.params.get("frame") == "last"]
    if len(first) < (1 if internal else MIN_CANDIDATES):
        raise QAError(f"{shot.shot_id} has {len(first)} keyframe candidates")
    if len({row.params.get("seed") for row in first}) != len(first):
        raise QAError(f"{shot.shot_id} keyframe seeds are not distinct")
    selected = [row for row in first if row.selected]
    if len(selected) != 1 and not internal:
        raise QAError(f"{shot.shot_id} must select exactly one opening frame")
    if needs_end_frame(shot):
        if len(last) < (1 if internal else MIN_CANDIDATES):
            raise QAError(f"{shot.shot_id} is missing end frames")
        chosen_last = [row for row in last if row.selected]
        if len(chosen_last) != 1:
            raise QAError(f"{shot.shot_id} must select exactly one end frame")
        if chosen_last[0].params.get("seed") != selected[0].params.get("seed"):
            raise QAError(f"{shot.shot_id} end frame does not match the opening seed")
    elif last:
        raise QAError(f"{shot.shot_id} should not have an end frame")
    blocked = [card.text for card in shot.on_screen_text]
    for row in rows:
        if row.node != "N8":
            raise QAError(f"{row.candidate_id} is not an N8 candidate")
        if not row.model or not row.uri:
            raise QAError(f"{row.candidate_id} is missing model or uri")
        prompt = str(row.params.get("prompt") or "")
        if NO_RENDERED_TEXT not in prompt:
            raise QAError(f"{row.candidate_id} prompt is missing the no-text constraint")
        if "seed" not in row.params:
            raise QAError(f"{row.candidate_id} params are missing seed")
        for text in blocked:
            if text and text in prompt:
                raise QAError(f"{row.candidate_id} prompt contains on-screen text")
        if row.qa.evaluator != "rule-select-v0":
            raise QAError(f"{row.candidate_id} uses an unexpected evaluator")
