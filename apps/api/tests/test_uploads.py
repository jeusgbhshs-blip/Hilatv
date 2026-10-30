"""Picture and link attachments for the input page. No workflow, no vendor call."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import WEB_ORIGINS, app

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_upload_image_and_reject_other_kinds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    client = TestClient(app)
    stored = client.post("/v1/uploads", files={"file": ("产品图.png", PNG, "image/png")})
    assert stored.status_code == 200
    body = stored.json()
    assert body["kind"] == "image"
    assert body["filename"] == "产品图.png"
    path = Path(body["uri"])
    assert path.is_file()
    assert path.read_bytes() == PNG
    assert path.is_relative_to(tmp_path.resolve())

    empty = client.post("/v1/uploads", files={"file": ("product.png", b"", "image/png")})
    assert empty.status_code == 400
    notes = client.post("/v1/uploads", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert notes.status_code == 415


def test_upload_respects_size_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_UPLOAD_MAX_BYTES", "4")
    client = TestClient(app)
    response = client.post("/v1/uploads", files={"file": ("product.png", b"12345", "image/png")})
    assert response.status_code == 413


def test_create_submits_image_and_url_without_starting_work(monkeypatch) -> None:
    seen: dict = {}

    async def fake_start_film(**kwargs):
        seen.update(kwargs)
        return "wf-test"

    monkeypatch.setattr("app.projects.start_film", fake_start_film)
    client = TestClient(app)
    rejected = client.post(
        "/v1/projects",
        json={"sentence": "做一条片子", "attachments": [{"kind": "video", "uri": "x"}]},
    )
    assert rejected.status_code == 422
    assert seen == {}

    created = client.post(
        "/v1/projects",
        json={
            "sentence": "做一条片子",
            "attachments": [
                {"kind": "image", "uri": "/tmp/product.png", "filename": "product.png"},
                {"kind": "url", "uri": "https://example.com/brochure"},
            ],
        },
    )
    assert created.status_code == 202
    assert created.json()["status"] == "running"
    assert seen["attachments"][0]["kind"] == "image"
    assert seen["attachments"][0]["filename"] == "product.png"
    assert seen["attachments"][1] == {
        "kind": "url",
        "uri": "https://example.com/brochure",
        "filename": None,
    }


def test_cors_reflects_the_web_origin() -> None:
    origin = WEB_ORIGINS[0]
    client = TestClient(app)
    allowed = client.get("/health", headers={"Origin": origin})
    assert allowed.headers["access-control-allow-origin"] == origin
    blocked = client.get("/health", headers={"Origin": "http://evil.example"})
    assert blocked.headers.get("access-control-allow-origin") != "http://evil.example"
