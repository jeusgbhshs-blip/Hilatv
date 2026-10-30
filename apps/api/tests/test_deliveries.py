"""Delivery API lists aspect, language, and duration without touching the web app."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.deliveries import _public, _replace_json, _write
from app.main import app
from workers.identity.session import open_session
from workers.nodes.n17_deliver.node import run as deliver
from workers.nodes.n17_deliver.sample import acceptance_request, storyboard
from workers.nodes.n17_deliver.support import build_gateway
from workers.workflow.store import init_project, project_path


def _session():
    ident = open_session()
    return ident, {"Authorization": f"Bearer {ident.token}"}


def test_versions_download_and_share(tmp_path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(root))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = build_gateway(tmp_path / "gateway")
    monkeypatch.setattr(
        "app.deliveries.run",
        lambda raw, **kwargs: deliver(raw, gateway=gateway, **kwargs),
    )
    project_id = "delivery17"
    request = acceptance_request(
        root,
        project_id=project_id,
        languages=["zh"],
        aspect_ratios=["9:16"],
        long_edge=160,
    )
    payload = request["payload"]
    assert isinstance(payload, dict)
    ident, headers = _session()
    init_project(
        project_id,
        status="completed",
        sentence="给我们的柱塞泵做个宣传片",
        script=payload["script"],
        brief=payload["brief"],
        brand_kit=payload["brand_kit"],
        master_plate=payload["master_path"],
        subject_tracks=payload["subject_tracks"],
        enterprise_id=ident.enterprise_id,
    )
    with TestClient(app, headers=headers) as client:
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
        assert version["qa_status"] == "pass"
        assert version["subject_box_source"] == "provided"
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
        assert shared.json()["expires_at"] > 0
        revoked = client.delete(f"/v1/projects/{project_id}/versions/{version['version_id']}/share")
        assert revoked.status_code == 204
        gone = client.get(shared.json()["share_path"])
        assert gone.status_code == 404


def test_client_cannot_choose_the_master_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    ident, headers = _session()
    init_project("pathguard", status="completed", enterprise_id=ident.enterprise_id)
    with TestClient(app, headers=headers) as client:
        absolute = client.post(
            "/v1/projects/pathguard/deliveries",
            json={"master_path": "/etc/passwd"},
        )
        assert absolute.status_code == 422
        traversal = client.post(
            "/v1/projects/pathguard/deliveries",
            json={"master_path": "../secret.mp4"},
        )
        assert traversal.status_code == 422


def test_snapshot_master_must_stay_inside_the_project(tmp_path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(root))
    script, brief, _tracks, _durations = storyboard()
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"not-a-project-file")
    ident, headers = _session()
    init_project(
        "abs17",
        status="completed",
        script=script,
        brief=brief,
        master_plate="/etc/passwd",
        enterprise_id=ident.enterprise_id,
    )
    escaped = project_path("trav17") / ".." / ".." / "secret.mp4"
    init_project(
        "trav17",
        status="completed",
        script=script,
        brief=brief,
        master_plate=str(escaped),
        enterprise_id=ident.enterprise_id,
    )
    linked = project_path("link17") / "plate.mp4"
    init_project(
        "link17",
        status="completed",
        script=script,
        brief=brief,
        master_plate=str(linked),
        enterprise_id=ident.enterprise_id,
    )
    linked.symlink_to(outside)
    with TestClient(app, headers=headers) as client:
        for project_id in ("abs17", "trav17", "link17"):
            response = client.post(f"/v1/projects/{project_id}/deliveries", json={})
            assert response.status_code == 422, response.text
            assert response.json()["detail"] == "成片母版不在项目目录内"


def test_export_cap_returns_429(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_N17_EXPORT_SLOTS", "0")
    ident, headers = _session()
    init_project("cap17", status="completed", enterprise_id=ident.enterprise_id)
    with TestClient(app, headers=headers) as client:
        response = client.post("/v1/projects/cap17/deliveries", json={})
    assert response.status_code == 429


def test_missing_qa_fields_do_not_count_as_pass() -> None:
    from workers.nodes.n17_deliver.schema import DeliveryVersion

    stored = {
        "version_id": "v",
        "aspect_ratio": "16:9",
        "language": "zh",
        "duration_s": 1,
        "width": 16,
        "height": 9,
        "path": "a.mp4",
        "picture_path": "b.mp4",
        "filters": "",
        "burn_filters": "",
        "geometry": [],
        "overlays": [],
        "spoken": [],
        "safe": {},
        "modes": {},
    }
    version = DeliveryVersion.model_validate(stored)
    assert version.subject_box_source == "default"
    assert version.qa_status == "needs_review"
    public = _public(
        "p",
        {
            "version_id": "v",
            "aspect_ratio": "16:9",
            "language": "zh",
            "duration_s": 1,
            "width": 16,
            "height": 9,
            "modes": {},
        },
    )
    assert public["subject_box_source"] == "default"
    assert public["qa_status"] == "needs_review"
    blank = _public(
        "p",
        {
            "version_id": "v",
            "aspect_ratio": "16:9",
            "language": "zh",
            "duration_s": 1,
            "width": 16,
            "height": 9,
            "modes": {},
            "subject_box_source": "",
            "qa_status": "",
        },
    )
    assert blank["subject_box_source"] == "default"
    assert blank["qa_status"] == "needs_review"


def test_deliveries_json_fsyncs_before_replace(tmp_path, monkeypatch) -> None:
    order: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fsync(fd: int) -> None:
        order.append("fsync")
        real_fsync(fd)

    def replace(src: str, dst: str) -> None:
        order.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr("app.deliveries.os.fsync", fsync)
    monkeypatch.setattr("app.deliveries.os.replace", replace)
    path = tmp_path / "deliveries.json"
    _replace_json(path, {"versions": []})
    assert order == ["fsync", "replace"]
    assert path.read_text(encoding="utf-8").strip().startswith("{")


def test_share_expires(tmp_path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(root))
    monkeypatch.setenv("HILATV_SHARE_TTL_S", "0")
    ident, headers = _session()
    init_project("share17", status="completed", enterprise_id=ident.enterprise_id)
    video = project_path("share17") / "clip.mp4"
    video.write_bytes(b"mp4")
    _write(
        "share17",
        {
            "versions": [
                {
                    "version_id": "v1",
                    "aspect_ratio": "16:9",
                    "language": "zh",
                    "duration_s": 2,
                    "width": 320,
                    "height": 180,
                    "modes": {"S01": "blur"},
                    "qa_status": "needs_review",
                    "subject_box_source": "default",
                    "download_path": "/v1/projects/share17/versions/v1/download",
                    "share_path": None,
                }
            ],
            "files": {"v1": str(video)},
            "shares": {},
            "rights": {},
        },
    )
    with TestClient(app, headers=headers) as client:
        shared = client.post("/v1/projects/share17/versions/v1/share")
        assert shared.status_code == 200, shared.text
        opened = client.get(shared.json()["share_path"])
        assert opened.status_code == 410
