"""Picture and link attachments for the input page. No workflow, no vendor call."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import WEB_ORIGINS, app
from workers.identity.session import open_session
from workers.workflow.store import init_project

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


def _client() -> TestClient:
    ident = open_session()
    return TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})


def _files_under(root: Path) -> list[Path]:
    folder = root / "uploads"
    if not folder.exists():
        return []
    return [path for path in folder.rglob("*") if path.is_file() and not path.name.startswith(".")]


def test_upload_image_returns_an_id_not_a_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    client = _client()
    stored = client.post("/v1/uploads", files={"file": ("产品图.png", PNG, "image/png")})
    assert stored.status_code == 200
    body = stored.json()
    assert body["kind"] == "image"
    assert body["filename"] == "产品图.png"
    assert body["upload_id"]
    assert "/" not in body["upload_id"]
    assert ".." not in body["upload_id"]
    assert "uri" not in body
    assert str(tmp_path) not in stored.text
    written = _files_under(tmp_path)
    assert len(written) == 1
    assert written[0].read_bytes() == PNG
    assert written[0].is_relative_to((tmp_path / "uploads").resolve())

    empty = client.post("/v1/uploads", files={"file": ("product.png", b"", "image/png")})
    assert empty.status_code == 400
    notes = client.post("/v1/uploads", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert notes.status_code == 415


def _upload(client: TestClient, name: str, payload: bytes, content_type: str):
    return client.post("/v1/uploads", files={"file": (name, payload, content_type)})


def test_upload_requires_matching_mime_and_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    client = _client()
    assert _upload(client, "logo.svg", SVG, "image/svg+xml").status_code == 415
    assert _upload(client, "logo.svg", PNG, "image/png").status_code == 415
    assert _upload(client, "logo.png", PNG, "image/svg+xml").status_code == 415
    assert _upload(client, "logo.png", PNG, "image/jpeg").status_code == 415
    assert _upload(client, "logo.jpg", PNG, "image/png").status_code == 415
    jpeg = _upload(client, "logo.jpg", PNG, "image/jpeg")
    assert jpeg.status_code == 200
    assert jpeg.json()["kind"] == "image"
    pdf = _upload(client, "spec.pdf", b"%PDF-1.4", "application/pdf")
    assert pdf.status_code == 200
    assert pdf.json()["kind"] == "pdf"
    assert "uri" not in pdf.json()


def test_upload_respects_size_limit_while_streaming(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_UPLOAD_MAX_BYTES", "4")
    client = _client()
    response = client.post("/v1/uploads", files={"file": ("product.png", b"12345", "image/png")})
    assert response.status_code == 413
    assert _files_under(tmp_path) == []


def test_create_rejects_server_paths_and_accepts_upload_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    seen: dict = {}

    async def fake_start_film(**kwargs):
        seen.update(kwargs)
        init_project(
            kwargs["project_id"],
            sentence=kwargs["sentence"],
            attachments=kwargs["attachments"],
            enterprise_id=kwargs.get("enterprise_id"),
        )
        return "wf-test"

    monkeypatch.setattr("app.projects.start_film", fake_start_film)
    client = _client()
    stored = client.post("/v1/uploads", files={"file": ("product.png", PNG, "image/png")})
    assert stored.status_code == 200
    upload_id = stored.json()["upload_id"]

    rejected = client.post(
        "/v1/projects",
        json={"sentence": "做一条片子", "attachments": [{"kind": "video", "uri": "x"}]},
    )
    assert rejected.status_code == 422
    assert seen == {}

    for uri in ("/etc/passwd", "/tmp/product.png", "/tmp/../etc/passwd", "../../etc/passwd"):
        response = client.post(
            "/v1/projects",
            json={
                "sentence": "做一条片子",
                "attachments": [{"kind": "image", "uri": uri, "filename": "product.png"}],
            },
        )
        assert response.status_code == 422
        assert uri not in response.text
        assert seen == {}

    dotted = client.post(
        "/v1/projects",
        json={
            "sentence": "做一条片子",
            "attachments": [{"kind": "image", "upload_id": "../" + "a" * 32}],
        },
    )
    assert dotted.status_code == 422
    assert seen == {}

    created = client.post(
        "/v1/projects",
        json={
            "sentence": "做一条片子",
            "attachments": [
                {"kind": "image", "upload_id": upload_id, "filename": "product.png"},
                {"kind": "url", "uri": "https://example.com/brochure"},
            ],
        },
    )
    assert created.status_code == 202
    assert created.json()["status"] == "running"
    assert str(tmp_path) not in created.text
    image = seen["attachments"][0]
    assert image["kind"] == "image"
    assert image["filename"] == "product.png"
    assert image["upload_id"] == upload_id
    resolved = Path(image["uri"])
    assert resolved.is_file()
    assert resolved.is_relative_to((tmp_path / "uploads").resolve())
    assert seen["attachments"][1] == {
        "kind": "url",
        "uri": "https://example.com/brochure",
        "filename": None,
    }

    status = client.get(f"/v1/projects/{seen['project_id']}")
    assert status.status_code == 200
    assert str(tmp_path) not in status.text
    assert "/etc/passwd" not in status.text
    listed = status.json()["attachments"]
    assert listed[0]["filename"] == "product.png"
    assert listed[0]["upload_id"] == upload_id
    assert "uri" not in listed[0]
    assert listed[1]["uri"] == "https://example.com/brochure"


def test_symlink_outside_uploads_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    seen: dict = {}

    async def fake_start_film(**kwargs):
        seen.update(kwargs)
        return "wf-test"

    monkeypatch.setattr("app.projects.start_film", fake_start_film)
    client = _client()
    stored = client.post("/v1/uploads", files={"file": ("product.png", PNG, "image/png")})
    upload_id = stored.json()["upload_id"]
    folder = tmp_path / "uploads" / upload_id
    stored_file = next(
        path for path in folder.iterdir() if path.is_file() and not path.name.startswith(".")
    )
    stored_file.unlink()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (folder / "product.png").symlink_to(secret)
    response = client.post(
        "/v1/projects",
        json={"sentence": "做一条片子", "attachments": [{"kind": "image", "upload_id": upload_id}]},
    )
    assert response.status_code == 422
    assert seen == {}
    assert "secret" not in response.text


def test_status_hides_a_stored_server_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    ident = open_session()
    init_project(
        "t11paths",
        sentence="做一条片子",
        enterprise_id=ident.enterprise_id,
        attachments=[
            {
                "kind": "image",
                "uri": "/etc/passwd",
                "filename": "产品图.png",
                "upload_id": "a" * 32,
            }
        ],
    )
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    response = client.get("/v1/projects/t11paths")
    assert response.status_code == 200
    assert "/etc/passwd" not in response.text
    image = response.json()["attachments"][0]
    assert image["filename"] == "产品图.png"
    assert "uri" not in image


def test_cors_reflects_the_web_origin() -> None:
    origin = WEB_ORIGINS[0]
    client = _client()
    allowed = client.get("/health", headers={"Origin": origin})
    assert allowed.headers["access-control-allow-origin"] == origin
    blocked = client.get("/health", headers={"Origin": "http://evil.example"})
    assert blocked.headers.get("access-control-allow-origin") != "http://evil.example"
