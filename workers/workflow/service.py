"""Start the film workflow from the API or the CLI."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from workers.logging import log_event
from workers.schemas.generation import GenerationSettings
from workers.schemas.generation import generation_settings as normalize_generation_settings
from workers.workflow.runtime import (
    build_worker,
    get_runtime,
    open_environment,
    task_queue,
    temporal_mode,
)
from workers.workflow.store import (
    contained_file,
    init_project,
    project_path,
    read_snapshot,
    update_snapshot,
)


def _storyboard_wait(value: int | None) -> int:
    """How long the cards stay open. ``0`` waits until the user continues."""

    if value is not None:
        return value
    raw = os.getenv("HILATV_STORYBOARD_WAIT_S", "").strip()
    if not raw:
        return 86400
    try:
        return int(raw)
    except ValueError:
        return 86400


def candidate_count(env_name: str) -> int:
    raw = os.getenv(env_name, "3").strip() or "3"
    try:
        value = int(raw)
    except ValueError:
        value = 3
    return min(8, max(1, value))


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
    skip_storyboard: bool | None = None,
    storyboard_wait_s: int | None = None,
    generation_settings: dict[str, Any] | GenerationSettings | None = None,
) -> dict[str, Any]:
    settings = normalize_generation_settings(generation_settings).model_dump(mode="json")
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
        "generation_settings": settings,
        "human_release": human_release is True,
        "internal_skip_review": os.getenv("HILATV_INTERNAL_SKIP_VISUAL_REVIEW", "0").strip() == "1",
        # Omitted means 直接出片. The product page sends false when it wants the cards.
        "skip_storyboard": True if skip_storyboard is None else bool(skip_storyboard),
        "storyboard_wait_s": _storyboard_wait(storyboard_wait_s),
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
    skip_storyboard: bool | None = None,
    workflow_id: str | None = None,
    owner_member_id: str | None = None,
    preserve_project: bool = False,
    generation_settings: dict[str, Any] | GenerationSettings | None = None,
) -> tuple[dict[str, Any], str]:
    if start_from and generation_settings is None:
        generation_settings = (read_snapshot(project_id) or {}).get("generation_settings")
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
        skip_storyboard=skip_storyboard,
        generation_settings=generation_settings,
    )
    if workflow_id is None:
        if start_from:
            workflow_id = f"{project_id}__{start_from}__{uuid.uuid4().hex[:8]}"
        else:
            workflow_id = project_id
    if preserve_project:
        # The draft submit transaction already durably claimed this exact run.
        # Reinitializing here would erase its owner, CAS revision and outbox.
        snapshot = read_snapshot(project_id)
        if snapshot is None or snapshot.get("workflow_id") != workflow_id:
            raise ValueError("project submission is not claimed")
        # A queued draft always uses the settings from the claimed revision.
        request["generation_settings"] = normalize_generation_settings(
            snapshot.get("generation_settings")
        ).model_dump(mode="json")
    elif start_from:
        previous = read_snapshot(project_id) or {}
        kept = contained_file(
            project_id, previous.get("deliverable") or previous.get("preview_path")
        )
        update_snapshot(
            project_id,
            status="running",
            error=None,
            deliverable=None,
            previous_deliverable=kept,
            preview_path=kept,
            quality_pass=False,
            delivery_status="needs_verification" if kept else "unavailable",
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
            owner_member_id=owner_member_id,
            concept_selection=concept_selection,
            generation_settings=request["generation_settings"],
            skip_storyboard=request["skip_storyboard"],
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


async def start_film(*, runtime: Any | None = None, **kwargs: Any) -> str:
    """Queue a run on the shared worker. Returns the workflow id."""

    # Connection failures happen before changing any project files.
    runtime = runtime or await get_runtime()
    request, workflow_id = prepare(**kwargs)
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


async def release_film(workflow_id: str) -> None:
    """Release the storyboard wait. The signal is ignored once the run has moved on."""

    runtime = await get_runtime()
    handle = runtime.client.get_workflow_handle(workflow_id)
    await handle.signal("release")


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
