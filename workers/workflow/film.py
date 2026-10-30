"""Temporal workflow for one sentence → one master MP4.

The workflow only schedules activities. Media and model calls stay in the
activities, which call the existing nodes. N12, N13, and N14 run together;
everything else is in order. A ``start_from`` rerun does not schedule upstream nodes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from workers.workflow.contract import (
        FINAL_NODE,
        PEERS,
        PHASE,
        PIPELINE,
        STORYBOARD_GATE,
        TIMEOUT_S,
    )

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
    "human_release",
    "skip_storyboard",
)


def needs_human_review(state: dict[str, Any], request: dict[str, Any]) -> bool:
    """True when a fallback clip was not vision-reviewed and nobody has released it.

    Live mode does not bypass this. Only ``human_release`` on the request,
    set by the explicit release action, continues into compose and delivery.
    Storyboard continue is a different signal and does not set this flag.
    """

    if request.get("human_release") is True:
        return False
    notes = state.get("shot_quality") or []
    if not isinstance(notes, list):
        return False
    return any(isinstance(item, dict) and item.get("needs_review") is True for item in notes)


def _storyboard_timeout(request: dict[str, Any]) -> timedelta | None:
    """Positive seconds wait for the cards. Zero or missing means no timer."""

    raw = request.get("storyboard_wait_s")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return None
    return timedelta(seconds=raw)


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
    if status == "needs_human_review":
        phase = "待人工复核"
    elif status == "completed":
        phase = "成片"
    else:
        phase = PHASE[node]
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
        self._storyboard_expired = False
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
        if state.get("held_for_review"):
            self._status = _view(
                request, "shot_director", state, status="needs_human_review", paused=True
            )
            return {
                "project_id": request["project_id"],
                "deliverable": None,
                "elapsed_s": state.get("elapsed_s"),
                "completed": list(state.get("completed") or []),
                "shot_quality": state.get("shot_quality"),
                "status": "needs_human_review",
            }
        if self._storyboard_expired:
            self._status = _view(request, STORYBOARD_GATE, state, status="timed_out", paused=False)
            return {
                "project_id": request["project_id"],
                "deliverable": None,
                "status": "timed_out",
                "cancellable": True,
                "completed": list(state.get("completed") or []),
            }
        self._status = _view(request, FINAL_NODE, state, status="completed", paused=False)
        return {
            "project_id": request["project_id"],
            "deliverable": state.get("deliverable"),
            "elapsed_s": state.get("elapsed_s"),
            "completed": list(state.get("completed") or []),
            "shot_quality": state.get("shot_quality"),
            "status": "completed",
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
            if node == STORYBOARD_GATE and request.get("skip_storyboard") is not True:
                state = await self._confirm_storyboard(request, state)
                if self._storyboard_expired:
                    return state
        if needs_human_review(state, request):
            patch = await self._call("hold_for_review", request, state)
            state = _merge(state, patch, "shot_director")
            state["held_for_review"] = True
            return state
        peers = [node for node in PEERS if PIPELINE.index(node) >= start_index]
        if peers:
            patches = await asyncio.gather(*(self._call(node, request, state) for node in peers))
            for node, patch in zip(peers, patches, strict=True):
                state = _merge(state, patch, node)
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
        view_node = "shot_director" if node == "hold_for_review" else node
        if request.get("pause_after") == node:
            self._status = _view(request, view_node, state, status="paused", paused=True)
            await workflow.wait_condition(lambda: self._release)
            self._release = False
        self._status = _view(request, view_node, state, status="running", paused=False)
        timeout = 30 if node == "hold_for_review" else TIMEOUT_S[node]
        result = await workflow.execute_activity(
            node,
            {
                "project_id": request["project_id"],
                "request": _public(request),
                "state": state,
            },
            start_to_close_timeout=timedelta(seconds=timeout),
            retry_policy=_retry(3),
        )
        patch = result.get("patch") if isinstance(result, dict) else None
        if not isinstance(patch, dict):
            raise ApplicationError(f"{node} returned no patch", non_retryable=True)
        return patch

    async def _confirm_storyboard(
        self,
        request: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Wait until the user leaves the storyboard cards, then reload edits.

        ``skip_storyboard`` never reaches this. Signals that arrived early still
        release the wait, because the signal flips ``_release`` before the check.
        """

        self._status = _view(request, STORYBOARD_GATE, state, status="paused", paused=True)
        timeout = _storyboard_timeout(request)
        try:
            await workflow.wait_condition(lambda: self._release, timeout=timeout)
        except TimeoutError:
            self._storyboard_expired = True
            await workflow.execute_activity(
                "storyboard_expire",
                {
                    "project_id": request["project_id"],
                    "request": _public(request),
                    "state": state,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_retry(1),
            )
            self._status = _view(request, STORYBOARD_GATE, state, status="timed_out", paused=False)
            return state
        self._release = False
        result = await workflow.execute_activity(
            "storyboard_sync",
            {
                "project_id": request["project_id"],
                "request": _public(request),
                "state": state,
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_retry(3),
        )
        patch = result.get("patch") if isinstance(result, dict) else None
        if not isinstance(patch, dict):
            raise ApplicationError("storyboard_sync returned no patch", non_retryable=True)
        merged = dict(state)
        merged.update(patch)
        self._status = _view(request, STORYBOARD_GATE, merged, status="running", paused=False)
        return merged

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
