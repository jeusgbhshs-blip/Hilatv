"""A needs_review shot does not become a delivery until a person releases it."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from temporalio import activity

from workers.workflow.activities import hold_for_review
from workers.workflow.contract import PIPELINE
from workers.workflow.fakes import CALLS, _make, reset
from workers.workflow.film import ProduceFilm, needs_human_review
from workers.workflow.runtime import build_worker, task_queue
from workers.workflow.service import make_request
from workers.workflow.store import init_project, load_checkpoint, read_snapshot, save_node


def test_release_is_required_before_a_master_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    asyncio.run(_hold_then_release())


def test_delivery_api_writes_nothing_while_held(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    init_project("heldapi", sentence="一句", status="needs_human_review", deliverable=None)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        status = client.get("/v1/projects/heldapi")
        assert status.status_code == 200
        assert status.json()["status"] == "needs_human_review"
        denied = client.post("/v1/projects/heldapi/deliveries", json={})
        assert denied.status_code == 409
    assert not (tmp_path / "heldapi" / "deliveries.json").is_file()


def test_human_release_is_the_only_bypass() -> None:
    state = {"shot_quality": [{"shot_id": "S01", "needs_review": True}]}
    assert needs_human_review(state, {}) is True
    assert needs_human_review(state, {"human_release": True}) is False
    assert needs_human_review({"shot_quality": [{"needs_review": False}]}, {}) is False


async def _hold_then_release() -> None:
    from temporalio.testing import WorkflowEnvironment

    reset()
    env = await WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=4)
    try:
        request = make_request(
            project_id="hold1",
            sentence="一句",
            start_from="shot_director",
            checkpoint={"completed": []},
        )
        init_project("hold1", sentence="一句", work_dir=request["work_dir"])
        worker = build_worker(env.client, executor, _activities())
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="hold1",
                task_queue=task_queue(),
            )
            held = await handle.result()
        master = Path(request["work_dir"]) / "n15" / "master.mp4"
        assert held["status"] == "needs_human_review"
        assert held["deliverable"] is None
        assert "n15_compose" not in CALLS
        assert "n12_music" not in CALLS
        snapshot = read_snapshot("hold1") or {}
        assert snapshot["status"] == "needs_human_review"
        assert not snapshot.get("deliverable")
        assert not master.is_file()
        assert not (Path(request["work_dir"]) / "deliveries.json").is_file()

        released = make_request(
            project_id="hold1",
            sentence="一句",
            start_from="n12_music",
            checkpoint=load_checkpoint("hold1"),
            human_release=True,
        )
        worker2 = build_worker(env.client, executor, _activities())
        async with worker2:
            handle2 = await env.client.start_workflow(
                ProduceFilm.run,
                released,
                id="hold1-release",
                task_queue=task_queue(),
            )
            done = await handle2.result()
        assert done["status"] == "completed"
        assert done["deliverable"]
        assert master.is_file()
        assert read_snapshot("hold1")["status"] == "completed"
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


def _activities() -> list:
    found = [_make(node) for node in PIPELINE if node != "shot_director"]
    found.append(_director)
    found.append(hold_for_review)
    return found


@activity.defn(name="shot_director")
def _director(payload: dict) -> dict:
    CALLS.append("shot_director")
    patch = {
        "shot_quality": [
            {
                "shot_id": "S01",
                "fallback_level": 4,
                "needs_review": True,
                "qa_passed": False,
                "reviewed": False,
            }
        ],
        "shot_clips": [{"shot_id": "S01", "path": "unused.mp4", "cards": []}],
    }
    save_node(str(payload["project_id"]), "shot_director", patch)
    return {"patch": patch}
