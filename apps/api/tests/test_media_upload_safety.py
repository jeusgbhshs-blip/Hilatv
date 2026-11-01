"""Private preview, bounded ingress and interrupted upload cleanup."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from gateway.media_bytes import render_png
from workers.assets import store
from workers.identity.session import open_session


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_ASSET_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    owner = open_session()
    return owner, TestClient(app, headers={"Authorization": f"Bearer {owner.token}"})


def test_asset_range_requires_owner_and_never_becomes_public(tmp_path, monkeypatch):
    _, client = _setup(tmp_path, monkeypatch)
    png = render_png(1)
    made = client.post("/v1/assets", files={"file": ("product.png", png, "image/png")})
    assert made.status_code == 200
    url = made.json()["url"]
    part = client.get(url, headers={"Range": "bytes=0-15"})
    assert part.status_code == 206 and part.content == png[:16]
    assert part.headers["content-range"] == f"bytes 0-15/{len(png)}"
    assert part.headers["cache-control"] == "private, no-store"
    assert client.get(url, headers={"Range": f"bytes={len(png) + 1}-"}).status_code == 416
    stranger = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert stranger.get(url, headers={"Range": "bytes=0-15"}).status_code == 404
    assert stranger.delete(url.removesuffix("/file")).status_code == 404
    assert TestClient(app).get(url, headers={"Range": "bytes=0-15"}).status_code == 401


def test_assets_sniff_content_and_reject_oversize_before_persist(tmp_path, monkeypatch):
    _, client = _setup(tmp_path, monkeypatch)
    assert (
        client.post(
            "/v1/assets", files={"file": ("fake.png", b"<script>bad</script>", "image/png")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/assets", files={"file": ("fake.jpg", render_png(1), "image/jpeg")}
        ).status_code
        == 422
    )
    monkeypatch.setattr(store, "MAX_BYTES", 4)
    result = client.post("/v1/assets", files={"file": ("large.png", b"12345", "image/png")})
    assert result.status_code == 413 and result.json()["detail"] == "文件过大"
    assert not list((tmp_path / "assets").rglob("file*"))


@pytest.mark.parametrize("endpoint", ["/v1/assets", "/v1/uploads"])
@pytest.mark.parametrize("declared", [None, "1"])
def test_chunked_and_false_lengths_are_bounded_and_spooled_files_closed(
    tmp_path, monkeypatch, endpoint, declared
):
    import starlette.formparsers as parser

    owner, _ = _setup(tmp_path, monkeypatch)
    limit = 1024 * 1024
    monkeypatch.setattr(store, "MAX_BYTES", limit)
    monkeypatch.setenv("HILATV_UPLOAD_MAX_BYTES", str(limit))
    opened = []
    original = parser.SpooledTemporaryFile

    def track(*args, **kwargs):
        handle = original(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(parser, "SpooledTemporaryFile", track)
    reads = []

    async def chunks():
        reads.append(1)
        yield (
            b'--boundary\r\nContent-Disposition: form-data; name="file"; '
            b'filename="p.png"\r\nContent-Type: image/png\r\n\r\n' + b"a" * limit
        )
        reads.append(2)
        yield b"b" * (70 * 1024)
        reads.append(3)
        yield b"never read" * limit

    headers = {
        "Authorization": f"Bearer {owner.token}",
        "Content-Type": "multipart/form-data; boundary=boundary",
    }
    if declared is not None:
        headers["Content-Length"] = declared

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(endpoint, headers=headers, content=chunks())

    response = asyncio.run(request())
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "文件过大"}
    assert reads == [1, 2]
    assert opened and all(handle.closed for handle in opened)
    assert not list(tmp_path.rglob("file*"))


@pytest.mark.parametrize("endpoint", ["/v1/assets", "/v1/uploads"])
def test_interrupted_multipart_closes_spooled_files(tmp_path, monkeypatch, endpoint):
    import starlette.formparsers as parser

    owner, _ = _setup(tmp_path, monkeypatch)
    opened = []
    original = parser.SpooledTemporaryFile

    def track(*args, **kwargs):
        handle = original(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(parser, "SpooledTemporaryFile", track)

    async def chunks():
        yield (
            b'--b\r\nContent-Disposition: form-data; name="file"; filename="p.png"\r\n\r\n'
            + b"x" * 4096
        )
        raise httpx.ReadError("client disconnected")

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                endpoint,
                content=chunks(),
                headers={
                    "Authorization": f"Bearer {owner.token}",
                    "Content-Type": "multipart/form-data; boundary=b",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 400
    assert opened and all(handle.closed for handle in opened)
    assert not list(tmp_path.rglob("file*"))


def test_content_length_guard_and_valid_multipart_overhead(tmp_path, monkeypatch):
    _, client = _setup(tmp_path, monkeypatch)
    too_big = client.post(
        "/v1/assets", content=b"", headers={"Content-Length": str(store.MAX_BYTES + 65537)}
    )
    assert too_big.status_code == 413 and too_big.json() == {"detail": "文件过大"}
    png = render_png(1)
    monkeypatch.setattr(store, "MAX_BYTES", len(png))
    valid = client.post(
        "/v1/assets", data={"kind": "product_image"}, files={"file": ("p.png", png, "image/png")}
    )
    assert valid.status_code == 200


@pytest.mark.parametrize("endpoint", ["/v1/assets", "/v1/uploads"])
def test_actual_twenty_mb_file_limit_rejects_before_asset_save(tmp_path, monkeypatch, endpoint):
    _, client = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("HILATV_UPLOAD_MAX_BYTES", str(20 * 1024 * 1024))

    def unexpected_save(*args, **kwargs):
        raise AssertionError("oversize files must not reach storage")

    monkeypatch.setattr(store, "save_asset", unexpected_save)
    result = client.post(
        endpoint, files={"file": ("large.png", b"x" * (20 * 1024 * 1024 + 1), "image/png")}
    )
    assert result.status_code == 413
    assert result.json() == {"detail": "文件过大"}
    assert not list(tmp_path.rglob("file*"))
    uploads = tmp_path / "projects" / "uploads"
    assert not uploads.exists() or not list(uploads.iterdir())


def test_ordinary_uploaded_attachment_reaches_n8_provider_body(tmp_path, monkeypatch):
    import base64
    import io
    import json
    from decimal import Decimal

    from PIL import Image

    from gateway.adapters.seedream import SeedreamAdapter
    from gateway.storage import MemoryObjectStore
    from gateway.tests.conftest import build_gateway
    from gateway.tests.test_media_adapters import MEDIA_ROUTES
    from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
    from workers.workflow import activities
    from workers.workflow.store import init_project

    _, client = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    seen = {}

    async def start(**kwargs):
        seen.update(kwargs)
        init_project(kwargs["project_id"], enterprise_id=kwargs["enterprise_id"])
        return "test-workflow"

    monkeypatch.setattr("app.projects.start_film", start)
    png = render_png(6)
    uploaded = client.post("/v1/uploads", files={"file": ("product.png", png, "image/png")})
    assert uploaded.status_code == 200
    made = client.post(
        "/v1/projects",
        json={
            "sentence": "产品广告",
            "attachments": [{"kind": "image", "upload_id": uploaded.json()["upload_id"]}],
        },
    )
    assert made.status_code == 202
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert body["image"].startswith("data:image/png;base64,")
        raw = base64.b64decode(body["image"].split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as image, Image.open(io.BytesIO(png)) as expected:
            assert image.getpixel((0, 0)) == expected.getpixel((0, 0))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()}]})

    engine_root = tmp_path / "gateway"
    engine_root.mkdir()
    engine = build_gateway(
        engine_root,
        routes=MEDIA_ROUTES,
        registry={
            "seedream": SeedreamAdapter(
                api_key="test-only",
                store=MemoryObjectStore(),
                transport=httpx.MockTransport(handler),
            )
        },
        limits=(True, Decimal("20"), Decimal("20")),
    )
    monkeypatch.setattr(activities, "_attempt", lambda: 1)
    monkeypatch.setattr("workers.nodes.n08_keyframe.node._default_gateway", lambda: engine)
    result = activities.n08_keyframe(
        {
            "project_id": made.json()["project_id"],
            "request": seen,
            "state": {"script": storyboard(shot())},
        }
    )
    assert len(result["patch"]["keyframes"]) == 3
    assert len(bodies) == 3
    logs = json.dumps(engine.store.list_logs())
    assert "data:image" not in logs and base64.b64encode(png).decode() not in logs
