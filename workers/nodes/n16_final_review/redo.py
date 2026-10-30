"""Run N16 redo decisions through N10, then charge the shared ledger once.

A decision is not a charge. ``open_project_budget`` moves only after N10 has
regenerated that shot. The same review batch (project, film, shot ids) is one
idempotency key, so two overlapping runs do not both spend.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from gateway.constants import NO_RENDERED_TEXT
from workers.logging import log_event
from workers.nodes.n16_final_review.schema import N16FinalInput, NodeRequest
from workers.qa.budget_store import open_project_budget
from workers.schemas.director import DecisionAction, DirectorDecision
from workers.workflow.store import load_checkpoint, project_path, read_snapshot, save_node

_REGEN = {DecisionAction.regenerate, DecisionAction.switch_model}
_WAIT_S = 30.0


def apply_redos(
    request: NodeRequest,
    payload: N16FinalInput,
    planned: list[DirectorDecision],
    *,
    gateway: Any,
) -> tuple[list[DirectorDecision], int, bool]:
    """Execute chargeable decisions, then spend once per regenerated shot.

    Returns ``(decisions, budget_taken, refused)``. ``refused`` means the
    whole batch did not fit, and nothing was spent. A duplicate of a batch
    that already ran returns no new decisions and does not spend again.
    """

    chargeable = [item for item in planned if item.action in _REGEN]
    if not chargeable:
        return planned, 0, False
    shot_ids = sorted({item.target.shot_id for item in chargeable})
    kept = [item for item in planned if item.action not in _REGEN]
    if not _openings_ready(request.project_id, shot_ids):
        return kept, 0, False
    key = _batch_key(request, payload, shot_ids)
    budget = open_project_budget(request.project_id)
    status = budget.begin_batch(len(shot_ids), key)
    if status == "refused":
        return [], 0, True
    if status in {"already", "pending"}:
        if status == "pending":
            waited = _wait(request.project_id, key)
            if waited == "free":
                status = budget.begin_batch(len(shot_ids), key)
            else:
                return kept, 0, False
        else:
            return kept, 0, False
        if status == "refused":
            return [], 0, True
        if status != "begun":
            return kept, 0, False
    produced = _execute(request, payload, chargeable, shot_ids, gateway=gateway)
    if produced != shot_ids:
        budget.abort_batch(key)
        log_event(
            "n16_redo_skipped",
            project_id=request.project_id,
            node="n16_final_review",
            shot_id=request.shot_id,
            attempt=request.attempt,
            produced=",".join(produced),
        )
        return kept, 0, False
    if not budget.finish_batch(len(shot_ids), key):
        return [], 0, True
    return planned, len(shot_ids), False


def _execute(
    request: NodeRequest,
    payload: N16FinalInput,
    chargeable: list[DirectorDecision],
    shot_ids: list[str],
    *,
    gateway: Any,
) -> list[str]:
    from workers.nodes.n10_video.node import run as run_video

    suffix = _suffix(chargeable)
    enterprise_id = _enterprise_id(request.project_id)
    state = load_checkpoint(request.project_id)
    frames = [item for item in state.get("keyframes") or [] if isinstance(item, dict)]
    produced: list[str] = []
    try:
        for shot_id in shot_ids:
            result = run_video(
                {
                    "project_id": request.project_id,
                    "shot_id": shot_id,
                    "attempt": request.attempt,
                    "payload": {
                        "script": payload.script.model_dump(mode="json"),
                        "candidates": frames,
                        "brief": payload.brief.model_dump(mode="json"),
                        "brand_kit": (
                            payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None
                        ),
                        "video_candidates": 3,
                        "prompt_suffix": suffix,
                        "enterprise_id": enterprise_id,
                    },
                },
                gateway=gateway,
                max_attempts=1,
            )
            rows = [
                item
                for item in result.payload.get("candidates") or []
                if isinstance(item, dict) and item.get("shot_id") == shot_id
            ]
            failed = set(result.payload.get("generation_failed") or [])
            if shot_id in failed or not rows:
                return produced
            _store_videos(request.project_id, rows)
            produced.append(shot_id)
    except Exception as exc:
        log_event(
            "n16_redo_failed",
            project_id=request.project_id,
            node="n16_final_review",
            shot_id=request.shot_id,
            attempt=request.attempt,
            error=str(exc)[:300],
        )
        return produced
    return produced


def _store_videos(project_id: str, rows: list[dict[str, Any]]) -> None:
    state = load_checkpoint(project_id)
    existing = [item for item in state.get("videos") or [] if isinstance(item, dict)]
    by_id = {str(item.get("candidate_id")): item for item in existing}
    for row in rows:
        by_id[str(row.get("candidate_id"))] = row
    save_node(project_id, "n10_video", {"videos": list(by_id.values())})


def _openings_ready(project_id: str, shot_ids: list[str]) -> bool:
    state = load_checkpoint(project_id)
    frames = state.get("keyframes") or []
    ready = {_shot_id(item) for item in frames if _is_opening(item)}
    return all(shot_id in ready for shot_id in shot_ids)


def _is_opening(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("node") != "N8" or item.get("selected") is not True:
        return False
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    return params.get("frame", "first") == "first"


def _shot_id(item: object) -> str:
    if isinstance(item, dict) and isinstance(item.get("shot_id"), str):
        return item["shot_id"]
    return ""


def _suffix(chargeable: list[DirectorDecision]) -> str:
    suffix = ""
    for item in chargeable:
        raw = item.changes.get("prompt_suffix")
        if isinstance(raw, str) and raw.strip():
            suffix = raw.strip()
            break
    if NO_RENDERED_TEXT not in suffix:
        suffix = f"{suffix} {NO_RENDERED_TEXT}".strip()
    return suffix


def _batch_key(request: NodeRequest, payload: N16FinalInput, shot_ids: list[str]) -> str:
    digest = _film_digest(request.project_id, payload.film_path)
    raw = f"n16:{request.attempt}:{digest}:{','.join(shot_ids)}"
    if len(raw) <= 200:
        return raw
    return "n16:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _film_digest(project_id: str, film_path: str) -> str:
    path = Path(film_path).expanduser()
    if not path.is_absolute():
        path = project_path(project_id, create=True) / path
    try:
        data = path.resolve().read_bytes()
    except OSError:
        data = film_path.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _enterprise_id(project_id: str) -> str | None:
    snapshot = read_snapshot(project_id)
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("enterprise_id")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _wait(project_id: str, key: str) -> str:
    deadline = time.monotonic() + _WAIT_S
    while time.monotonic() < deadline:
        status = open_project_budget(project_id).batch_status(key)
        if status != "pending":
            return status
        time.sleep(0.05)
    return open_project_budget(project_id).batch_status(key)
