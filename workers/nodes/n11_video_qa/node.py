"""N11 video review. Sample 4 frames a second, veto a bad frame, splice clean stretches."""

from __future__ import annotations

import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

from workers.logging import log_event
from workers.nodes.n11_video_qa.qa import QAError, check
from workers.nodes.n11_video_qa.schema import N11Input, NodeRequest, NodeResult
from workers.nodes.runtime import Deadline, candidate_uuid
from workers.qa.director import decide
from workers.qa.frames import SAMPLE_FPS, sample_frames, write_mp4
from workers.qa.pixels import open_image
from workers.qa.rules import inspect_frames
from workers.qa.scores import is_quality_pass
from workers.qa.service import review_shot
from workers.qa.settings import RetryBudget
from workers.qa.splice import plan_splice
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.director import DecisionAction, DecisionTarget, DirectorDecision

NODE = "n11_video_qa"


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    payload = N11Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway if gateway is not None else _default_gateway()
    budget = RetryBudget()
    last_error: QAError | None = None
    for try_index in range(1, max_attempts + 1):
        try:
            result = _execute(request, payload, gateway=gateway, timeout_s=timeout_s, budget=budget)
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=try_index,
                error=str(exc),
            )
            continue
        return result
    raise QAError(f"n11_video_qa failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    payload: N11Input,
    *,
    gateway: Any,
    timeout_s: float,
    budget: RetryBudget,
) -> NodeResult:
    deadline = Deadline(timeout_s, node=NODE)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=request.attempt,
    )
    scored: list[tuple[Candidate, QAReport, list[Image.Image], list[bool]]] = []
    for candidate in payload.candidates:
        if request.shot_id and candidate.shot_id != request.shot_id:
            continue
        deadline.check()
        frames, good = _frames(candidate, payload)
        report = review_shot(
            _review_payload(request, candidate, payload),
            gateway=gateway,
            frames=frames or None,
            image=frames[0] if len(frames) == 1 else None,
        )
        scored.append((candidate, report, frames, good))
    if not scored:
        raise QAError("n11 had no candidates for the requested shot")
    updated, decisions, splices = _choose(scored, request=request, gateway=gateway, budget=budget)
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "candidates": [row.model_dump(mode="json") for row in updated],
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "splices": splices,
            "shot_ids": sorted({row.shot_id for row in updated}),
        },
        attempt=request.attempt,
    )


def _choose(
    scored: list[tuple[Candidate, QAReport, list[Image.Image], list[bool]]],
    *,
    request: NodeRequest,
    gateway: Any,
    budget: RetryBudget,
) -> tuple[list[Candidate], list[DirectorDecision], list[dict[str, Any]]]:
    by_shot: dict[str, list[tuple[Candidate, QAReport, list[Image.Image], list[bool]]]] = (
        defaultdict(list)
    )
    for item in scored:
        by_shot[item[0].shot_id].append(item)
    updated: list[Candidate] = []
    decisions: list[DirectorDecision] = []
    splices: list[dict[str, Any]] = []
    for shot_id, rows in by_shot.items():
        best = max(rows, key=lambda item: item[1].total)
        decision = decide(
            best[1],
            node="N10",
            shot_id=shot_id,
            attempt=request.attempt,
            model=best[0].model,
            prompt=str(best[0].params.get("prompt") or ""),
            gateway=gateway,
            project_id=request.project_id,
            budget=budget,
        )
        passed = is_quality_pass(best[1])
        extra: Candidate | None = None
        if not passed:
            extra, plan = _try_splice(rows, request=request, shot_id=shot_id, gateway=gateway)
            if extra is not None and plan is not None and is_quality_pass(extra.qa):
                decision = DirectorDecision(
                    action=DecisionAction.pass_,
                    target=DecisionTarget(node="N11", shot_id=shot_id),
                    reason="候选前后段互补，拼接合格片段",
                    changes={"segments": [segment.__dict__ for segment in plan]},
                    max_attempts_left=decision.max_attempts_left,
                )
                splices.append(
                    {
                        "shot_id": shot_id,
                        "uri": extra.uri,
                        "segments": [segment.__dict__ for segment in plan],
                    }
                )
                passed = True
        chosen = best[0].candidate_id if passed and extra is None else None
        if extra is not None:
            chosen = extra.candidate_id
        for candidate, report, _frames, _good in rows:
            updated.append(
                candidate.model_copy(
                    update={"qa": report, "selected": candidate.candidate_id == chosen}
                )
            )
        if extra is not None:
            updated.append(extra.model_copy(update={"selected": True}))
        decisions.append(decision)
    return updated, decisions, splices


def _try_splice(
    rows: list[tuple[Candidate, QAReport, list[Image.Image], list[bool]]],
    *,
    request: NodeRequest,
    shot_id: str,
    gateway: Any,
) -> tuple[Candidate | None, list[Any] | None]:
    tracks = [
        (candidate.candidate_id, good, frames)
        for candidate, _report, frames, good in rows
        if frames and good
    ]
    if len(tracks) < 2:
        return None, None
    plan = plan_splice(tracks)
    if not plan or len(plan) < 2:
        return None, None
    frames_for = {candidate.candidate_id: frames for candidate, _r, frames, _g in rows}
    pieces: list[Image.Image] = []
    for segment in plan:
        start = int(round(segment.start_s * SAMPLE_FPS))
        end = int(round(segment.end_s * SAMPLE_FPS))
        pieces.extend(frames_for[segment.candidate_id][start:end])
    if not pieces:
        return None, None
    folder = Path(tempfile.mkdtemp(prefix="hilatv-splice-"))
    path = folder / f"{shot_id}.mp4"
    write_mp4(pieces, path, fps=SAMPLE_FPS)
    report = review_shot(
        {
            "project_id": request.project_id,
            "shot_id": shot_id,
            "node": "n11_video",
            "candidate_uri": str(path),
            "purpose": "拼接后的镜头",
            "visual": "合格片段衔接",
        },
        gateway=gateway,
        frames=pieces,
    )
    if not is_quality_pass(report):
        return None, None
    anchor = rows[0][0]
    candidate = Candidate(
        candidate_id=candidate_uuid(request.project_id, shot_id, "N11", "splice", 0),
        shot_id=shot_id,
        node="N11",
        model=anchor.model,
        params={
            "seed": 0,
            "spliced": True,
            "segments": [segment.__dict__ for segment in plan],
            "prompt": str(anchor.params.get("prompt") or ""),
        },
        uri=str(path),
        qa=report,
        selected=True,
    )
    return candidate, plan


def _frames(candidate: Candidate, payload: N11Input) -> tuple[list[Image.Image], list[bool]]:
    uri = candidate.uri
    path = uri[7:] if uri.startswith("file://") else uri
    frames: list[Image.Image] = []
    if path.lower().endswith((".mp4", ".mov", ".webm")):
        frames = sample_frames(Path(path))
    else:
        image = open_image(uri)
        if image is not None:
            frames = [image]
    if not frames:
        return [], []
    anchor = open_image(payload.anchors.get(candidate.shot_id, ""))
    _findings, good = inspect_frames(
        frames,
        anchor=anchor,
        expected_faces=payload.expected_faces.get(candidate.shot_id, 0),
    )
    return frames, good


def _review_payload(
    request: NodeRequest, candidate: Candidate, payload: N11Input
) -> dict[str, Any]:
    return {
        "project_id": request.project_id,
        "shot_id": candidate.shot_id,
        "node": "n11_video",
        "candidate_uri": candidate.uri,
        "anchor_uri": payload.anchors.get(candidate.shot_id, ""),
        "expected_faces": payload.expected_faces.get(candidate.shot_id, 0),
        "model": candidate.model,
        "purpose": str(candidate.params.get("purpose") or ""),
        "visual": str(candidate.params.get("visual") or ""),
        "voiceover": str(candidate.params.get("voiceover") or ""),
        "shot_size": str(candidate.params.get("shot_size") or ""),
        "shot_type": str(candidate.params.get("camera") or ""),
        "generation_mode": str(candidate.params.get("generation_mode") or ""),
        "prompt": str(candidate.params.get("prompt") or ""),
    }


def _default_gateway() -> Any:
    from gateway.service import get_gateway

    return get_gateway()
