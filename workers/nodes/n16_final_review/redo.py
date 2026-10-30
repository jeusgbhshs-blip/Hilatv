"""Run N16 redo decisions through N10, then charge the shared ledger once.

A decision is not a charge. ``open_project_budget`` moves only after N10 has
regenerated that shot. The same review batch (project, film, shot ids) is one
idempotency key, so two overlapping runs do not both spend.

Every shot N10 returns is recorded in the ledger (``note_generated``) before
it is saved. A generation that comes back after the save deadline is billed
but not saved, and a worker that crashes after saving is billed when its
reservation expires. Real generations are never dropped from the ledger.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gateway.constants import NO_RENDERED_TEXT
from workers.logging import log_event
from workers.nodes.n16_final_review.schema import N16FinalInput, NodeRequest
from workers.qa.budget_store import open_project_budget, reserve_ttl_s
from workers.schemas.director import DecisionAction, DirectorDecision
from workers.workflow.store import load_checkpoint, project_path, read_snapshot, save_node

_REGEN = {DecisionAction.regenerate, DecisionAction.switch_model}
_WAIT_S = 30.0
NODE = "n16_final_review"


def apply_redos(
    request: NodeRequest,
    payload: N16FinalInput,
    planned: list[DirectorDecision],
    *,
    gateway: Any,
) -> tuple[list[DirectorDecision], int, bool]:
    """Execute chargeable decisions, then spend once per regenerated shot.

    Returns ``(decisions, budget_taken, refused)``. ``budget_taken`` counts the
    saved shots that carry a redo decision. A shot N10 produced after the save
    deadline is still billed in the ledger, but has no decision. ``refused`` means the
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
    budget = open_project_budget(request.project_id, node=NODE)
    status, token = budget.begin_batch(len(shot_ids), key)
    if status == "refused":
        return [], 0, True
    if status in {"already", "pending"}:
        if status == "pending":
            waited = _wait(request.project_id, key)
            if waited == "free":
                status, token = budget.begin_batch(len(shot_ids), key)
            else:
                return kept, 0, False
        else:
            return kept, 0, False
        if status == "refused":
            return [], 0, True
        if status != "begun":
            return kept, 0, False
    # Monotonic, and strictly shorter than the wall-clock reservation TTL.
    deadline = time.monotonic() + _redo_deadline_s()
    generated: list[str] = []

    def note(shot_id: str) -> None:
        # Recorded before the save, so a crash after the save is still billed.
        generated.append(shot_id)
        if token:
            budget.note_generated(key, token, shot_id)

    produced = _execute(
        request, payload, chargeable, shot_ids, gateway=gateway, deadline=deadline, note=note
    )
    if not generated:
        if token:
            budget.abort_batch(key, token)
        log_event(
            "n16_redo_skipped",
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=request.attempt,
        )
        return kept, 0, False
    outcome = budget.finish_batch(len(generated), key, token)
    if outcome not in {"taken", "audited", "already"}:
        return [], 0, True
    unsaved = sorted(set(generated) - set(produced))
    if unsaved:
        # N10 returned after the save deadline: billed in the ledger, not saved.
        # ``budget_taken`` stays the number of redo decisions (QA invariant).
        log_event(
            "n16_redo_unsaved",
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=request.attempt,
            billed_unsaved=len(unsaved),
            shots=unsaved,
        )
    if not produced:
        return kept, 0, False
    saved = set(produced)
    if saved == set(shot_ids):
        return planned, len(shot_ids), False
    chosen = [item for item in planned if item.action not in _REGEN or item.target.shot_id in saved]
    return chosen, len(produced), False


def _redo_deadline_s() -> float:
    """Half the reservation TTL. Default TTL is 900s, so this is 450s.

    450s is the longest this N10 loop runs. The reservation stays on the
    wall clock for 900s so another process can see it. This deadline uses
    ``time.monotonic`` so a wall-clock step cannot keep saves going after
    the worker's own budget. 450s is strictly inside the 900s reservation.
    """

    return reserve_ttl_s() / 2


def _execute(
    request: NodeRequest,
    payload: N16FinalInput,
    chargeable: list[DirectorDecision],
    shot_ids: list[str],
    *,
    gateway: Any,
    deadline: float,
    note: Callable[[str], None],
) -> list[str]:
    """Run N10 per shot. Returns the shots that were saved before the deadline.

    ``note`` is called for every shot N10 produced, before the deadline check
    and before the save, so a generation is billed even when it is not saved.
    """

    from workers.nodes.n10_video.node import run as run_video

    suffix = _suffix(chargeable)
    enterprise_id = _enterprise_id(request.project_id)
    state = load_checkpoint(request.project_id)
    frames = [item for item in state.get("keyframes") or [] if isinstance(item, dict)]
    produced: list[str] = []
    try:
        for shot_id in shot_ids:
            if time.monotonic() >= deadline:
                break
            remaining = deadline - time.monotonic()
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
                timeout_s=max(0.05, remaining),
            )
            rows = [
                item
                for item in result.payload.get("candidates") or []
                if isinstance(item, dict) and item.get("shot_id") == shot_id
            ]
            failed = set(result.payload.get("generation_failed") or [])
            if shot_id in failed or not rows:
                return produced
            note(shot_id)
            if time.monotonic() >= deadline:
                # Past the save deadline: recorded as used above, not saved.
                break
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
