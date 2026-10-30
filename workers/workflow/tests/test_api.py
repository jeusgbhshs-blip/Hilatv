"""HTTP create / status / rerun / WebSocket. The worker runs fakes, not N8/N15."""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import open_session
from workers.workflow.fakes import CALLS, FAIL, FAKE_ACTIVITIES, reset
from workers.workflow.runtime import set_activities, shutdown_runtime


def test_create_progress_and_rerun(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_TEMPORAL_MODE", "embedded")
    monkeypatch.setenv("HILATV_TEMPORAL_CLOCK", "skip")
    monkeypatch.setenv("HILATV_TASK_QUEUE", "hilatv-api-test")
    reset()
    set_activities(FAKE_ACTIVITIES)
    try:
        ident = open_session()
        headers = {"Authorization": f"Bearer {ident.token}"}
        first, second = asyncio.run(_run(headers))
    finally:
        set_activities(None)
    assert first["status"] == "completed"
    assert any(item["message"] == "第 3 镜：正在生成画面" for item in first["events"])
    assert second["status"] == "completed"
    assert CALLS.count("n01_brief") == 2
    assert CALLS.count("n08_keyframe") == 3
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/v1/projects/{first['project_id']}/progress",
            headers=headers,
        ) as socket:
            seen = []
            while True:
                item = socket.receive_json()
                seen.append(item)
                if item.get("status") == "completed":
                    break
    assert any(item.get("message") == "第 3 镜：正在生成画面" for item in seen)


async def _run(headers: dict[str, str]) -> tuple[dict, dict]:
    transport = httpx.ASGITransport(app=app)
    try:
        return await _drive(transport, headers)
    finally:
        await shutdown_runtime()


async def _drive(transport: httpx.ASGITransport, headers: dict[str, str]) -> tuple[dict, dict]:
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
    ) as client:
        created = await client.post(
            "/v1/projects",
            json={"sentence": "给我们的柱塞泵做个15秒宣传片"},
        )
        assert created.status_code == 202
        project_id = created.json()["project_id"]
        first = await _wait(client, project_id)
        assert first["phase"] == "成片"
        download = await client.get(f"/v1/projects/{project_id}/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("video/mp4")

        FAIL.add("n08_keyframe")
        created = await client.post("/v1/projects", json={"sentence": "再做一条"})
        assert created.status_code == 202
        failed_id = created.json()["project_id"]
        failed = await _wait(client, failed_id)
        assert failed["status"] == "failed"
        FAIL.clear()
        rerun = await client.post(f"/v1/projects/{failed_id}/rerun", json={"node": "n08_keyframe"})
        assert rerun.status_code == 202
        second = await _wait(client, failed_id)
        first["events"] = await _events(client, project_id)
        second["project_id"] = failed_id
        first["project_id"] = project_id
        return first, second


async def _wait(client: httpx.AsyncClient, project_id: str) -> dict:
    deadline = time.monotonic() + 30
    last: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/projects/{project_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"completed", "failed"}:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(last)


async def _events(client: httpx.AsyncClient, project_id: str) -> list[dict]:
    body = (await client.get(f"/v1/projects/{project_id}")).json()
    return list(body.get("events") or [])
