"""Embedded Temporal dev server, or a client pointed at TEMPORAL_ADDRESS.

``embedded`` does not use the Compose service. ``remote`` does, and expects
``hilatv worker`` to poll the task queue. Workflow cache is off so a new worker
picks up an open run immediately instead of waiting out a sticky queue.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

_OVERRIDE: list[Any] | None = None
_RUNTIME: Runtime | None = None
_LOCK = asyncio.Lock()


def set_activities(activities: list[Any] | None) -> None:
    """Tests swap in fakes before the worker starts. ``None`` restores production."""

    global _OVERRIDE
    _OVERRIDE = activities


def resolve_activities() -> list[Any]:
    if _OVERRIDE is not None:
        return _OVERRIDE
    from workers.workflow.activities import ACTIVITIES

    return list(ACTIVITIES)


def task_queue() -> str:
    return os.getenv("HILATV_TASK_QUEUE", "hilatv").strip() or "hilatv"


def temporal_mode() -> str:
    return os.getenv("HILATV_TEMPORAL_MODE", "embedded").strip() or "embedded"


def temporal_clock() -> str:
    """``local`` keeps real time. ``skip`` is the in-process test server."""

    return os.getenv("HILATV_TEMPORAL_CLOCK", "local").strip() or "local"


def build_worker(
    client: Any,
    executor: ThreadPoolExecutor,
    activities: list[Any] | None = None,
) -> Any:
    from temporalio.worker import Worker

    from workers.workflow.film import ProduceFilm

    return Worker(
        client,
        task_queue=task_queue(),
        workflows=[ProduceFilm],
        activities=activities if activities is not None else resolve_activities(),
        activity_executor=executor,
        max_cached_workflows=0,
        max_concurrent_activities=8,
        build_id="hilatv-t10",
    )


async def open_environment(clock: str | None = None) -> Any:
    from temporalio.testing import WorkflowEnvironment

    chosen = clock or temporal_clock()
    if chosen == "skip":
        return await WorkflowEnvironment.start_time_skipping()
    return await WorkflowEnvironment.start_local()


@dataclass
class Runtime:
    client: Any
    env: Any | None
    stop: asyncio.Event | None
    task: asyncio.Task[None] | None
    executor: ThreadPoolExecutor | None


async def get_runtime() -> Runtime:
    global _RUNTIME
    async with _LOCK:
        if _RUNTIME is not None:
            return _RUNTIME
        if temporal_mode() == "remote":
            from temporalio.client import Client

            address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
            client = await Client.connect(address)
            _RUNTIME = Runtime(client=client, env=None, stop=None, task=None, executor=None)
            return _RUNTIME
        env = await open_environment()
        executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hilatv-activity")
        worker = build_worker(env.client, executor)
        stop = asyncio.Event()

        async def _serve() -> None:
            async with worker:
                await stop.wait()

        task = asyncio.create_task(_serve())
        _RUNTIME = Runtime(
            client=env.client,
            env=env,
            stop=stop,
            task=task,
            executor=executor,
        )
        return _RUNTIME


async def shutdown_runtime() -> None:
    global _RUNTIME
    if _RUNTIME is None:
        return
    async with _LOCK:
        runtime = _RUNTIME
        _RUNTIME = None
    if runtime is None:
        return
    if runtime.stop is not None:
        runtime.stop.set()
    if runtime.task is not None:
        try:
            await runtime.task
        except asyncio.CancelledError:
            pass
    if runtime.env is not None:
        await runtime.env.shutdown()
    if runtime.executor is not None:
        runtime.executor.shutdown(wait=False, cancel_futures=True)
