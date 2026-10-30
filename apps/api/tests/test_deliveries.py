"""Delivery API lists aspect, language, and duration without touching the web app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from workers.nodes.n17_deliver.node import run as deliver
from workers.nodes.n17_deliver.sample import acceptance_request
from workers.nodes.n17_deliver.support import build_gateway
from workers.workflow.store import init_project


def test_versions_download_and_share(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = build_gateway(tmp_path / "gateway")
    monkeypatch.setattr(
        "app.deliveries.run",
        lambda raw, **kwargs: deliver(raw, gateway=gateway, **kwargs),
    )
    request = acceptance_request(
        tmp_path / "case",
        languages=["zh"],
        aspect_ratios=["9:16"],
        long_edge=160,
    )
    payload = request["payload"]
    assert isinstance(payload, dict)
    project_id = "delivery17"
    init_project(
        project_id,
        status="completed",
        sentence="给我们的柱塞泵做个宣传片",
        script=payload["script"],
        brief=payload["brief"],
        brand_kit=payload["brand_kit"],
        master_plate=payload["master_path"],
        subject_tracks=payload["subject_tracks"],
    )
    with TestClient(app) as client:
        created = client.post(
            f"/v1/projects/{project_id}/deliveries",
            json={"languages": ["zh"], "aspect_ratios": ["9:16"], "long_edge": 160},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert len(body["versions"]) == 1
        version = body["versions"][0]
        assert version["aspect_ratio"] == "9:16"
        assert version["language"] == "zh"
        assert version["width"] < version["height"]
        assert "download_path" in version
        listed = client.get(f"/v1/projects/{project_id}/versions")
        assert listed.status_code == 200
        assert listed.json()["versions"][0]["version_id"] == version["version_id"]
        downloaded = client.get(version["download_path"])
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("video/mp4")
        assert downloaded.content[:8] != b""
        shared = client.post(f"/v1/projects/{project_id}/versions/{version['version_id']}/share")
        assert shared.status_code == 200
        opened = client.get(shared.json()["share_path"])
        assert opened.status_code == 200
        assert opened.content == downloaded.content
