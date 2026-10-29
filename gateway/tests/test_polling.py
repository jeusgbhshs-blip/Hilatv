"""Queued → running → success, failure, and timeout."""

from __future__ import annotations

import pytest

from gateway.errors import AdapterError, AdapterTimeout
from gateway.polling import TaskSnapshot, TaskState, poll_task


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def test_queued_running_then_succeeded() -> None:
    clock = Clock()
    snaps = [
        TaskSnapshot(TaskState.QUEUED),
        TaskSnapshot(TaskState.RUNNING),
        TaskSnapshot(TaskState.SUCCEEDED, result_url="https://cdn.example/clip.mp4", duration_s=5),
    ]

    def fetch() -> TaskSnapshot:
        return snaps.pop(0)

    done = poll_task(fetch, timeout_s=30, interval_s=2, now=clock.now, sleep=clock.sleep)
    assert done.result_url == "https://cdn.example/clip.mp4"
    assert clock.sleeps == [2, 2]
    assert snaps == []


def test_failure_stops_the_poll() -> None:
    clock = Clock()
    snaps = [
        TaskSnapshot(TaskState.QUEUED),
        TaskSnapshot(TaskState.FAILED, error="content rejected"),
    ]

    def fetch() -> TaskSnapshot:
        return snaps.pop(0)

    with pytest.raises(AdapterError, match="content rejected"):
        poll_task(fetch, timeout_s=30, interval_s=2, now=clock.now, sleep=clock.sleep)
    assert clock.t == 2


def test_timeout_while_still_running() -> None:
    clock = Clock()

    def fetch() -> TaskSnapshot:
        return TaskSnapshot(TaskState.RUNNING)

    with pytest.raises(AdapterTimeout, match="running"):
        poll_task(fetch, timeout_s=5, interval_s=2, now=clock.now, sleep=clock.sleep)
    assert clock.t >= 5


def test_success_without_a_url_is_an_error() -> None:
    with pytest.raises(AdapterError, match="result url"):
        poll_task(
            lambda: TaskSnapshot(TaskState.SUCCEEDED),
            timeout_s=5,
            interval_s=1,
            now=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
