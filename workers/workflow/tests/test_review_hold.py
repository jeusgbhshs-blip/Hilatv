"""A needs_review shot does not become a delivery until a person releases it."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from temporalio import activity

from workers.workflow.activities import hold_for_review
from workers.workflow.contract import PIPELINE
from workers.workflow.fakes import (
    CALLS,
    _make,
    mark_failed,
    reset,
    storyboard_expire,
    storyboard_sync,
)
from workers.workflow.film import ProduceFilm, needs_human_review
from workers.workflow.runtime import build_worker, task_queue
from workers.workflow.service import make_request
from workers.workflow.store import (
    init_project,
    load_checkpoint,
    read_events,
    read_snapshot,
    save_node,
    update_snapshot,
)


def test_release_is_required_before_a_master_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    asyncio.run(_hold_then_release())


def test_delivery_api_writes_nothing_while_held(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    from workers.identity.session import open_session

    ident = open_session()
    init_project(
        "heldapi",
        sentence="一句",
        status="needs_human_review",
        deliverable=None,
        enterprise_id=ident.enterprise_id,
    )
    from fastapi.testclient import TestClient

    from app.main import app

    headers = {"Authorization": f"Bearer {ident.token}"}
    with TestClient(app, headers=headers) as client:
        status = client.get("/v1/projects/heldapi")
        assert status.status_code == 200
        assert status.json()["status"] == "needs_human_review"
        denied = client.post("/v1/projects/heldapi/deliveries", json={})
        assert denied.status_code == 409
    assert not (tmp_path / "heldapi" / "deliveries.json").is_file()


def test_storyboard_continue_still_stops_for_needs_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    asyncio.run(_continue_then_hold())
    master = tmp_path / "boardhold" / "n15" / "master.mp4"
    assert not master.is_file()
    assert not (tmp_path / "boardhold" / "deliveries.json").is_file()
    snapshot = read_snapshot("boardhold") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    from fastapi.testclient import TestClient

    from app.main import app
    from workers.identity.session import open_session

    ident = open_session()
    update_snapshot("boardhold", enterprise_id=ident.enterprise_id)
    headers = {"Authorization": f"Bearer {ident.token}"}
    with TestClient(app, headers=headers) as client:
        denied = client.post("/v1/projects/boardhold/deliveries", json={})
        assert denied.status_code == 409
    assert not (tmp_path / "boardhold" / "deliveries.json").is_file()


def test_release_passes_project_fields_and_records_the_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    captured: dict[str, dict] = {}

    async def fake_run(**kwargs):
        captured["cli"] = kwargs
        return {"status": "completed", "deliverable": None}

    async def fake_start(**kwargs):
        captured["api"] = kwargs
        return "wf-release"

    monkeypatch.setenv("HILATV_SESSION_SECRET", "t14-release-test")
    monkeypatch.setattr("workers.workflow.cli.run_and_wait", fake_run)
    monkeypatch.setattr("workers.workflow.service.start_film", fake_start)
    from workers.identity.session import mint_session_for_tests

    cli_ident = mint_session_for_tests("11111111-1111-4111-8111-111111111111")
    api_ident = mint_session_for_tests("22222222-2222-4222-8222-222222222222")
    init_project(
        "relcli",
        sentence="一句",
        status="needs_human_review",
        enterprise_id=cli_ident.enterprise_id,
        concept_selection="concept-cli",
        brand_id="brand-cli",
    )
    init_project(
        "relapi",
        sentence="一句",
        status="needs_human_review",
        enterprise_id=api_ident.enterprise_id,
        concept_selection="concept-api",
        brand_id="brand-api",
    )
    from workers.workflow.cli import main

    assert main(["release", "--session", cli_ident.token, "relcli"]) == 0
    cli_event = _released_event("relcli")
    assert cli_event["project_id"] == "relcli"
    assert isinstance(cli_event["ts"], float) and cli_event["ts"] > 0
    assert cli_event["releaser"] == cli_ident.member_id
    assert captured["cli"]["enterprise_id"] == cli_ident.enterprise_id
    assert captured["cli"]["concept_selection"] == "concept-cli"
    assert captured["cli"]["human_release"] is True
    assert captured["cli"]["start_from"] == "n12_music"

    from fastapi.testclient import TestClient

    from app.main import app

    headers = {"Authorization": f"Bearer {api_ident.token}"}
    with TestClient(app, headers=headers) as client:
        response = client.post("/v1/projects/relapi/human-review/release")
    assert response.status_code == 202, response.text
    api_event = _released_event("relapi")
    assert api_event["project_id"] == "relapi"
    assert isinstance(api_event["ts"], float) and api_event["ts"] > 0
    assert api_event["releaser"] == api_ident.member_id
    assert captured["api"]["enterprise_id"] == api_ident.enterprise_id
    assert captured["api"]["concept_selection"] == "concept-api"
    assert captured["api"]["human_release"] is True
    assert captured["api"]["start_from"] == "n12_music"


def _released_event(project_id: str) -> dict:
    found = [
        item for item in read_events(project_id) if item.get("type") == "human_review_released"
    ]
    assert len(found) == 1
    return found[0]


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


async def _continue_then_hold() -> None:
    from temporalio.testing import WorkflowEnvironment

    from workers.workflow.storyboard import claim_continue

    reset()
    env = await WorkflowEnvironment.start_time_skipping()
    executor = ThreadPoolExecutor(max_workers=4)
    try:
        request = make_request(
            project_id="boardhold",
            sentence="一句",
            skip_storyboard=False,
            storyboard_wait_s=0,
        )
        init_project(
            "boardhold",
            sentence="一句",
            work_dir=request["work_dir"],
            workflow_id="boardhold",
            skip_storyboard=False,
        )
        worker = build_worker(env.client, executor, _storyboard_activities())
        async with worker:
            handle = await env.client.start_workflow(
                ProduceFilm.run,
                request,
                id="boardhold",
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
            update_snapshot(
                "boardhold",
                status="paused",
                storyboard_gate="hold",
                workflow_id="boardhold",
            )
            assert claim_continue("boardhold") == "boardhold"
            await handle.signal(ProduceFilm.release)
            held = await handle.result()
        assert held["status"] == "needs_human_review"
        assert held["deliverable"] is None
        assert "storyboard_sync" in CALLS
        assert "n10_video" in CALLS
        assert "shot_director" in CALLS
        assert "n12_music" not in CALLS
        assert "n15_compose" not in CALLS
        master = Path(request["work_dir"]) / "n15" / "master.mp4"
        assert not master.is_file()
        assert not (Path(request["work_dir"]) / "deliveries.json").is_file()
    finally:
        await env.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)


def _storyboard_activities() -> list:
    found = [_make(node) for node in PIPELINE if node != "shot_director"]
    found.extend([_director, hold_for_review, storyboard_sync, storyboard_expire, mark_failed])
    return found


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
