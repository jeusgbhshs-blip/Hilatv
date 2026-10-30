"""Temporal workflow for one sentence → one master MP4.

The workflow only schedules activities. Media and model calls stay in the
activities, which call the existing nodes. N13 and N14 run together; everything
else is in order. A ``start_from`` rerun does not schedule upstream nodes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from workers.workflow.contract import FINAL_NODE, PEERS, PHASE, PIPELINE, TIMEOUT_S

_PUBLIC = (
    "sentence",
    "brand_kit",
    "brand_id",
    "attachments",
    "work_dir",
    "keyframe_candidates",
    "video_candidates",
    "fail_nodes",
    "enterprise_id",
    "concept_selection",
)


def _retry(attempts: int) -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=20),
        maximum_attempts=attempts,
    )


def _public(request: dict[str, Any]) -> dict[str, Any]:
    return {key: request.get(key) for key in _PUBLIC}


def _merge(state: dict[str, Any], patch: dict[str, Any], node: str) -> dict[str, Any]:
    merged = dict(state)
    merged.update(patch)
    completed = [item for item in (state.get("completed") or []) if item != node]
    completed.append(node)
    merged["completed"] = completed
    return merged


def _view(
    request: dict[str, Any],
    node: str,
    state: dict[str, Any],
    *,
    status: str,
    paused: bool,
) -> dict[str, Any]:
    phase = "成片" if status == "completed" else PHASE[node]
    return {
        "project_id": request["project_id"],
        "status": status,
        "phase": phase,
        "node": node,
        "paused": paused,
        "completed": list(state.get("completed") or []),
    }


@workflow.defn(name="ProduceFilm")
class ProduceFilm:
    def __init__(self) -> None:
        self._release = False
        self._status: dict[str, Any] = {}

    @workflow.run
    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        start = request.get("start_from") or PIPELINE[0]
        if start not in PIPELINE:
            raise ApplicationError(f"unknown node {start}", non_retryable=True)
        raw_checkpoint = request.get("checkpoint") or {}
        if not isinstance(raw_checkpoint, dict):
            raise ApplicationError("checkpoint must be an object", non_retryable=True)
        state = dict(raw_checkpoint)
        state.setdefault("completed", [])
        self._status = _view(request, start, state, status="running", paused=False)
        try:
            state = await self._pipeline(request, state, PIPELINE.index(start))
        except ActivityError as exc:
            await self._fail(request, exc)
            raise
        self._status = _view(request, FINAL_NODE, state, status="completed", paused=False)
        return {
            "project_id": request["project_id"],
            "deliverable": state.get("deliverable"),
            "elapsed_s": state.get("elapsed_s"),
            "completed": list(state.get("completed") or []),
        }

    @workflow.signal
    def release(self) -> None:
        self._release = True

    @workflow.query
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def _pipeline(
        self,
        request: dict[str, Any],
        state: dict[str, Any],
        start_index: int,
    ) -> dict[str, Any]:
        skip = set(PEERS) | {FINAL_NODE}
        for node in PIPELINE:
            if node in skip or PIPELINE.index(node) < start_index:
                continue
            patch = await self._call(node, request, state)
            state = _merge(state, patch, node)
        peers = [node for node in PEERS if PIPELINE.index(node) >= start_index]
        if len(peers) == 2:
            first, second = await asyncio.gather(
                self._call(peers[0], request, state),
                self._call(peers[1], request, state),
            )
            state = _merge(state, first, peers[0])
            state = _merge(state, second, peers[1])
        elif len(peers) == 1:
            patch = await self._call(peers[0], request, state)
            state = _merge(state, patch, peers[0])
        if PIPELINE.index(FINAL_NODE) >= start_index:
            patch = await self._call(FINAL_NODE, request, state)
            state = _merge(state, patch, FINAL_NODE)
        return state

    async def _call(
        self,
        node: str,
        request: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if request.get("pause_after") == node:
            self._status = _view(request, node, state, status="paused", paused=True)
            await workflow.wait_condition(lambda: self._release)
            self._release = False
        self._status = _view(request, node, state, status="running", paused=False)
        result = await workflow.execute_activity(
            node,
            {
                "project_id": request["project_id"],
                "request": _public(request),
                "state": state,
            },
            start_to_close_timeout=timedelta(seconds=TIMEOUT_S[node]),
            retry_policy=_retry(3),
        )
        patch = result.get("patch") if isinstance(result, dict) else None
        if not isinstance(patch, dict):
            raise ApplicationError(f"{node} returned no patch", non_retryable=True)
        return patch

    async def _fail(self, request: dict[str, Any], exc: ActivityError) -> None:
        node = str(getattr(exc, "activity_type", None) or self._status.get("node") or "workflow")
        cause = getattr(exc, "cause", None)
        label = type(cause).__name__ if cause is not None else "ActivityError"
        await workflow.execute_activity(
            "mark_failed",
            {
                "project_id": request["project_id"],
                "node": node,
                "error": f"{node} failed ({label})",
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_retry(1),
        )
