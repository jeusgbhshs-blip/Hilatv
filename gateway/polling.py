"""Async vendor task poller: queued → running → succeeded, failed, or timeout."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gateway.errors import AdapterError, AdapterTimeout


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class TaskSnapshot:
    state: TaskState
    result_url: str | None = None
    error: str | None = None
    duration_s: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)


def poll_task(
    fetch: Callable[[], TaskSnapshot],
    *,
    timeout_s: float,
    interval_s: float,
    now: Callable[[], float],
    sleep: Callable[[float], None],
) -> TaskSnapshot:
    if timeout_s <= 0:
        raise AdapterTimeout("poll timeout")
    deadline = now() + timeout_s
    while True:
        snap = fetch()
        if snap.state == TaskState.SUCCEEDED:
            if not snap.result_url:
                raise AdapterError("task succeeded without a result url")
            return snap
        if snap.state == TaskState.FAILED:
            raise AdapterError(snap.error or "task failed")
        if snap.state not in {TaskState.QUEUED, TaskState.RUNNING}:
            raise AdapterError(f"unknown task state: {snap.state}")
        if now() >= deadline:
            raise AdapterTimeout(f"poll timeout after {timeout_s}s in state {snap.state}")
        sleep(min(interval_s, max(0.0, deadline - now())))
