"""Worker restart and rerun. Activities are fakes, so no model or ffmpeg runs."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from temporalio.client import WorkflowFailureError

from workers.workflow.fakes import CALLS, FAKE_ACTIVITIES, reset
from workers.workflow.film import ProduceFilm
from workers.workflow.runtime import build_worker, task_queue
from workers.workflow.service import make_request
from workers.workflow.store import init_project, load_checkpoint


def test_worker_restart_resumes_without_repeating_upstream(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    asyncio.run(_resume(tmp_path))


def test_rerun_skips_upstream_nodes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    asyncio.run(_rerun(tmp_path))


def test_storyboard_gate_waits_for_release(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    asyncio.run(_storyboard_gate())


def test_skip_storyboard_runs_through(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    asyncio.run(_skip_storyboard())


def test_unknown_node_does_not_run_activities(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    asyncio.run(_unknown(tmp_path))


async def _resume(tmp_path: Path) -> None:
    from temporalio.testing import WorkflowEnvironment

    reset()
    env = await WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        request = make_request(
            project_id="resume1",
            sentence="给我们的柱塞泵做个15秒宣传片",
            pause_after="n04_script",
        )
        init_project("resume1", sentence=request["sentence"], work_dir=request["work_dir"])
        worker = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="resume1",
                task_queue=task_queue(),
            )
            status: dict = {}
            paused = False
            for _ in range(200):
                try:
                    status = await handle.query(ProduceFilm.status)
                except Exception:
                    status = {}
                if status.get("paused") and status.get("node") == "n04_script":
                    paused = True
                    break
                await asyncio.sleep(0.05)
            assert paused, status
            assert CALLS.count("n01_brief") == 1
            assert "n04_script" not in CALLS
        worker2 = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker2:
            await handle.signal(ProduceFilm.release)
            result = await handle.result()
        assert result["deliverable"]
        assert CALLS.count("n01_brief") == 1
        assert CALLS.count("n15_compose") == 1
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


async def _rerun(tmp_path: Path) -> None:
    reset()
    env_mod = __import__("temporalio.testing", fromlist=["WorkflowEnvironment"])
    env = await env_mod.WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        request = make_request(
            project_id="rerun1",
            sentence="给我们的柱塞泵做个15秒宣传片",
            fail_nodes=["n08_keyframe"],
        )
        init_project("rerun1", sentence=request["sentence"], work_dir=request["work_dir"])
        worker = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker:
            failed = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="rerun1",
                task_queue=task_queue(),
            )
            with pytest.raises(WorkflowFailureError):
                await failed.result()
            checkpoint = load_checkpoint("rerun1")
            assert "n06_voiceover" in checkpoint["completed"]
            assert "n08_keyframe" not in checkpoint["completed"]
            before = CALLS.count("n01_brief")
            assert before == 1
            again = make_request(
                project_id="rerun1",
                sentence=request["sentence"],
                start_from="n08_keyframe",
                checkpoint=checkpoint,
            )
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                again,
                id="rerun1-again",
                task_queue=task_queue(),
            )
            result = await handle.result()
        assert result["deliverable"]
        assert CALLS.count("n01_brief") == before
        assert CALLS.count("n08_keyframe") == 2
        assert CALLS.count("n15_compose") == 1
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


async def _storyboard_gate() -> None:
    from temporalio.testing import WorkflowEnvironment

    reset()
    env = await WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        request = make_request(
            project_id="board1",
            sentence="给我们的柱塞泵做个15秒宣传片",
            skip_storyboard=False,
        )
        init_project(
            "board1",
            sentence=request["sentence"],
            work_dir=request["work_dir"],
            skip_storyboard=False,
        )
        worker = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="board1",
                task_queue=task_queue(),
            )
            paused = False
            status: dict = {}
            for _ in range(200):
                try:
                    status = await handle.query(ProduceFilm.status)
                except Exception:
                    status = {}
                if (
                    status.get("paused")
                    and status.get("node") == "n09_keyframe_qa"
                    and "n10_video" not in CALLS
                    and "n09_keyframe_qa" in CALLS
                ):
                    paused = True
                    break
                await asyncio.sleep(0.05)
            assert paused, status
            assert "storyboard_sync" not in CALLS
            await handle.signal(ProduceFilm.release)
            result = await handle.result()
        assert result["deliverable"]
        assert CALLS.count("n09_keyframe_qa") == 1
        assert CALLS.count("n10_video") == 1
        assert "storyboard_sync" in CALLS
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


async def _skip_storyboard() -> None:
    from temporalio.testing import WorkflowEnvironment

    reset()
    env = await WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        request = make_request(
            project_id="skip1",
            sentence="给我们的柱塞泵做个15秒宣传片",
            skip_storyboard=True,
        )
        init_project(
            "skip1",
            sentence=request["sentence"],
            work_dir=request["work_dir"],
            skip_storyboard=True,
        )
        worker = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="skip1",
                task_queue=task_queue(),
            )
            result = await handle.result()
        assert result["deliverable"]
        assert CALLS.count("n09_keyframe_qa") == 1
        assert CALLS.count("n10_video") == 1
        assert "storyboard_sync" not in CALLS
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


async def _unknown(tmp_path: Path) -> None:
    reset()
    env_mod = __import__("temporalio.testing", fromlist=["WorkflowEnvironment"])
    env = await env_mod.WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        request = make_request(project_id="badnode", sentence="一句话", start_from="n99_missing")
        init_project("badnode", sentence=request["sentence"], work_dir=request["work_dir"])
        worker = build_worker(env.client, executor, FAKE_ACTIVITIES)
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="badnode",
                task_queue=task_queue(),
            )
            with pytest.raises(WorkflowFailureError):
                await handle.result()
        assert CALLS == []
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)
