"""Timeouts, shot-level parallelism, and Candidate ids shared by N8 and N10."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from workers.schemas.asset import Candidate, QAReport, QAScores
from workers.schemas.script import Shot


class Deadline:
    def __init__(self, timeout_s: float, *, node: str) -> None:
        if timeout_s <= 0:
            raise TimeoutError(f"{node} exceeded timeout")
        self._end = time.monotonic() + timeout_s
        self.node = node

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError(f"{self.node} exceeded timeout")


def workers_for(count: int) -> int:
    raw = os.getenv("HILATV_SHOT_WORKERS", "4").strip() or "4"
    try:
        limit = int(raw)
    except ValueError:
        limit = 4
    return max(1, min(max(limit, 1), max(count, 1)))


def run_parallel(
    shots: list[Shot],
    fn: Any,
    *,
    workers: int,
) -> list[tuple[str, Any, BaseException | None]]:
    """Run one callable per shot. A failure is returned, not raised, except timeout."""

    if not shots:
        return []
    output: list[tuple[str, Any, BaseException | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(shots)))) as pool:
        futures = {pool.submit(fn, shot): shot.shot_id for shot in shots}
        for future in as_completed(futures):
            shot_id = futures[future]
            try:
                output.append((shot_id, future.result(), None))
            except TimeoutError:
                raise
            except Exception as exc:
                output.append((shot_id, None, exc))
    return output


def variant_seeds(shot_id: str, kind: str, count: int) -> list[int]:
    digest = hashlib.sha256(f"{kind}:{shot_id}".encode()).hexdigest()
    base = int(digest[:8], 16) % 1_000_000
    return [base + index * 17 for index in range(count)]


def candidate_uuid(project_id: str, shot_id: str, node: str, kind: str, seed: int) -> str:
    name = f"hilatv:{project_id}:{shot_id}:{node}:{kind}:{seed}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def placeholder_qa(*, selected: bool) -> QAReport:
    note = (
        "Selected by lowest seed until N9/N11 (T12)."
        if selected
        else "Held until N9/N11 (T12). Not selected."
    )
    return QAReport(
        scores=QAScores(
            product_fidelity=8,
            motion_quality=8,
            aesthetics=8,
            prompt_match=8,
            artifact_free=8,
        ),
        hard_fail=[],
        total=8.0,
        evaluator="rule-select-v0",
        notes=note,
    )


def intended_model(gateway: Any, task: str, shot_type: str, language: str | None) -> str:
    routes = getattr(gateway, "routes", None)
    fallback = "mock-image" if task == "image" else "mock-video"
    if routes is None:
        return fallback
    try:
        return str(routes.resolve(task, shot_type, language).primary.model)
    except Exception:
        return fallback


def model_from_logs(
    gateway: Any,
    *,
    project_id: str,
    node: str,
    shot_id: str,
    seed: int,
    task: str,
) -> str:
    store = getattr(gateway, "store", None)
    if store is None or not hasattr(store, "list_logs"):
        return ""
    try:
        rows = store.list_logs(project_id=project_id)
    except Exception:
        return ""
    found = ""
    for row in rows:
        if row.get("node") != node or row.get("shot_id") != shot_id:
            continue
        if row.get("task") != task or row.get("status") != "ok":
            continue
        params = row.get("params") or {}
        if params.get("seed") != seed:
            continue
        found = str(row.get("model") or "")
    return found


def choose_id(candidates: list[Candidate], *, preferred_model: str) -> str:
    """Prefer the route's model when a candidate actually used it, else the lowest seed."""

    preferred = [item for item in candidates if item.model == preferred_model]
    group = preferred or list(candidates)
    winner = min(group, key=lambda item: (int(item.params.get("seed", 0)), item.candidate_id))
    return winner.candidate_id


def apply_selection(candidates: list[Candidate], chosen_ids: set[str]) -> list[Candidate]:
    updated: list[Candidate] = []
    for item in candidates:
        selected = item.candidate_id in chosen_ids
        updated.append(
            item.model_copy(update={"selected": selected, "qa": placeholder_qa(selected=selected)})
        )
    return updated


def object_stores(gateway: Any) -> list[Any]:
    registry = getattr(gateway, "registry", None) or {}
    found: list[Any] = []
    for adapter in registry.values():
        store = getattr(adapter, "store", None)
        if store is not None and all(store is not item for item in found):
            found.append(store)
    return found


def read_bytes(gateway: Any, uri: str) -> tuple[Any, bytes] | None:
    for store in object_stores(gateway):
        try:
            return store, store.get(uri)
        except Exception:
            continue
    return None
