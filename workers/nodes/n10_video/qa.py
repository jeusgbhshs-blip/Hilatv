"""Quality check for N10. Frame-by-frame scoring waits for N11 (T12)."""

from __future__ import annotations

from gateway.constants import NO_RENDERED_TEXT
from workers.nodes.n10_video.schema import NodeResult
from workers.nodes.shot_meta import shot_family
from workers.schemas.asset import Candidate
from workers.schemas.script import GenerationMode, Script, Shot

MIN_CANDIDATES = 3


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> list[Candidate]:
    if result.node != "n10_video":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n10_video result is not ok")
    script = Script.model_validate(result.payload.get("script"))
    wanted = set(result.payload.get("shot_ids") or [])
    if not wanted:
        raise QAError("n10_video names no shots")
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
    if shot.generation_mode is GenerationMode.motion_graphics:
        if rows:
            raise QAError(f"{shot.shot_id} is motion graphics and must not call a video model")
        return
    if len(rows) < MIN_CANDIDATES:
        raise QAError(f"{shot.shot_id} has {len(rows)} video candidates")
    if len({row.params.get("seed") for row in rows}) != len(rows):
        raise QAError(f"{shot.shot_id} video seeds are not distinct")
    selected = [row for row in rows if row.selected]
    if len(selected) != 1:
        raise QAError(f"{shot.shot_id} must select exactly one video")
    family = shot_family(shot)
    blocked = [card.text for card in shot.on_screen_text]
    for row in rows:
        if row.node != "N10":
            raise QAError(f"{row.candidate_id} is not an N10 candidate")
        if not row.model or not row.uri:
            raise QAError(f"{row.candidate_id} is missing model or uri")
        prompt = str(row.params.get("prompt") or "")
        if NO_RENDERED_TEXT not in prompt:
            raise QAError(f"{row.candidate_id} prompt is missing the no-text constraint")
        for text in blocked:
            if text and text in prompt:
                raise QAError(f"{row.candidate_id} prompt contains on-screen text")
        if row.params.get("seed") is None:
            raise QAError(f"{row.candidate_id} params are missing seed")
        if row.params.get("duration") not in (5, 10):
            raise QAError(f"{row.candidate_id} duration is not 5 or 10 seconds")
        _audit_trim(shot, row)
        if family == "product" and row.params.get("motion_strength") != "low":
            raise QAError(f"{row.candidate_id} product shot is not low motion")
        if row.qa.evaluator != "rule-select-v0":
            raise QAError(f"{row.candidate_id} uses an unexpected evaluator")


def _audit_trim(shot: Shot, row: Candidate) -> None:
    start = _number(row, "trim_start_s")
    end = _number(row, "trim_end_s")
    head = _number(row, "head_margin_s")
    tail = _number(row, "tail_margin_s")
    output = _number(row, "output_duration_s")
    if head <= 0 or tail <= 0:
        raise QAError(f"{row.candidate_id} dropped the transition margin")
    if abs((end - start) - shot.duration_s) > 0.05:
        raise QAError(f"{row.candidate_id} trim window is not the shot length")
    if abs(output - shot.duration_s) > 0.25:
        raise QAError(f"{row.candidate_id} was not trimmed to duration_s")
    if not str(row.params.get("image_url") or ""):
        raise QAError(f"{row.candidate_id} has no opening frame")


def _number(row: Candidate, key: str) -> float:
    value = row.params.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise QAError(f"{row.candidate_id} params are missing {key}")
    return float(value)
