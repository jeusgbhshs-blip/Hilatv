"""Start the film workflow from the API or the CLI."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from workers.logging import log_event
from workers.workflow.runtime import (
    build_worker,
    get_runtime,
    open_environment,
    task_queue,
    temporal_mode,
)
from workers.workflow.store import init_project, project_path, update_snapshot


def candidate_count(env_name: str) -> int:
    raw = os.getenv(env_name, "3").strip() or "3"
    try:
        value = int(raw)
    except ValueError:
        value = 3
    return min(8, max(3, value))


def make_request(
    *,
    project_id: str,
    sentence: str,
    brand_kit: dict[str, Any] | None = None,
    brand_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    keyframe_candidates: int | None = None,
    video_candidates: int | None = None,
    start_from: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    fail_nodes: list[str] | None = None,
    pause_after: str | None = None,
    enterprise_id: str | None = None,
    concept_selection: str | None = None,
    human_release: bool = False,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "sentence": sentence,
        "brand_kit": brand_kit,
        "brand_id": brand_id,
        "attachments": list(attachments or []),
        "work_dir": str(project_path(project_id, create=True)),
        "keyframe_candidates": (
            candidate_count("HILATV_KEYFRAME_CANDIDATES")
            if keyframe_candidates is None
            else keyframe_candidates
        ),
        "video_candidates": (
            candidate_count("HILATV_VIDEO_CANDIDATES")
            if video_candidates is None
            else video_candidates
        ),
        "start_from": start_from,
        "checkpoint": checkpoint,
        "fail_nodes": list(fail_nodes or []),
        "pause_after": pause_after,
        "enterprise_id": enterprise_id,
        "concept_selection": concept_selection,
        "human_release": human_release is True,
    }


def prepare(
    *,
    project_id: str,
    sentence: str,
    brand_kit: dict[str, Any] | None = None,
    brand_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    keyframe_candidates: int | None = None,
    video_candidates: int | None = None,
    start_from: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    fail_nodes: list[str] | None = None,
    pause_after: str | None = None,
    enterprise_id: str | None = None,
    concept_selection: str | None = None,
    human_release: bool = False,
    workflow_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    request = make_request(
        project_id=project_id,
        sentence=sentence,
        brand_kit=brand_kit,
        brand_id=brand_id,
        attachments=attachments,
        keyframe_candidates=keyframe_candidates,
        video_candidates=video_candidates,
        start_from=start_from,
        checkpoint=checkpoint,
        fail_nodes=fail_nodes,
        pause_after=pause_after,
        enterprise_id=enterprise_id,
        concept_selection=concept_selection,
        human_release=human_release,
    )
    if workflow_id is None:
        if start_from:
            workflow_id = f"{project_id}__{start_from}__{uuid.uuid4().hex[:8]}"
        else:
            workflow_id = project_id
    if start_from:
        update_snapshot(
            project_id,
            status="running",
            error=None,
            deliverable=None,
            elapsed_s=None,
            finished_at=None,
            message=f"正在从 {start_from} 继续",
            workflow_id=workflow_id,
        )
    else:
        init_project(
            project_id,
            sentence=sentence,
            brand_kit=brand_kit,
            brand_id=brand_id,
            attachments=list(attachments or []),
            keyframe_candidates=request["keyframe_candidates"],
            video_candidates=request["video_candidates"],
            work_dir=request["work_dir"],
            workflow_id=workflow_id,
            enterprise_id=enterprise_id,
            concept_selection=concept_selection,
        )
    log_event(
        "workflow_started",
        project_id=project_id,
        node=start_from or "n01_brief",
        attempt=1,
        workflow_id=workflow_id,
    )
    return request, workflow_id


async def _await_result(client: Any, request: dict[str, Any], workflow_id: str) -> dict[str, Any]:
    from workers.workflow.film import ProduceFilm

    handle = await client.start_workflow(
        ProduceFilm.run,
        request,
        id=workflow_id,
        task_queue=task_queue(),
    )
    result = await handle.result()
    return dict(result)


def _stamp(project_id: str, started: float, result: dict[str, Any]) -> dict[str, Any]:
    elapsed = round(time.perf_counter() - started, 3)
    update_snapshot(project_id, elapsed_s=elapsed)
    result["elapsed_s"] = elapsed
    result["timing_recorded"] = True
    result["live"] = os.getenv("HILATV_LIVE", "0").strip() == "1"
    return result


async def start_film(**kwargs: Any) -> str:
    """Queue a run on the shared worker. Returns the workflow id."""

    request, workflow_id = prepare(**kwargs)
    runtime = await get_runtime()
    from workers.workflow.film import ProduceFilm

    await runtime.client.start_workflow(
        ProduceFilm.run,
        request,
        id=workflow_id,
        task_queue=task_queue(),
    )
    return workflow_id


async def run_and_wait(**kwargs: Any) -> dict[str, Any]:
    """Run to the first master file. Embedded mode starts its own dev server."""

    request, workflow_id = prepare(**kwargs)
    project_id = request["project_id"]
    started = time.perf_counter()
    try:
        if temporal_mode() == "remote":
            from temporalio.client import Client

            client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
            result = await _await_result(client, request, workflow_id)
        else:
            env = await open_environment()
            executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hilatv-activity")
            try:
                worker = build_worker(env.client, executor)
                async with worker:
                    result = await _await_result(env.client, request, workflow_id)
            finally:
                await env.shutdown()
                executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        _stamp(project_id, started, {})
        raise
    return _stamp(project_id, started, result)


async def serve_worker() -> None:
    """Poll TEMPORAL_ADDRESS until the process is stopped. For remote mode."""

    from temporalio.client import Client

    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hilatv-activity")
    worker = build_worker(client, executor)
    try:
        async with worker:
            await asyncio_forever()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


async def asyncio_forever() -> None:
    import asyncio

    await asyncio.Future()
