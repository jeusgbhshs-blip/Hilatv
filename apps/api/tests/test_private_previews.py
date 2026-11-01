"""Object-store previews stay private, scoped and seekable."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from gateway.storage import MemoryObjectStore
from workers.identity.session import open_session
from workers.media.assets import materialize_project_asset
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.workflow.store import init_project, project_path
from workers.workflow.storyboard import prepare_gate


def _image():
    image = Image.new("RGB", (320, 320), "white")
    ImageDraw.Draw(image).rectangle((70, 80, 210, 220), fill="blue")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("scheme", ["oss", "s3"])
def test_storyboard_object_preview_and_range_are_owned(tmp_path, monkeypatch, scheme):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    owner = open_session()
    init_project("p1", enterprise_id=owner.enterprise_id)
    store = MemoryObjectStore(scheme=scheme)
    png = _image()
    uri = store.put("keyframes/frame.png", png, "image/png")
    engine = SimpleNamespace(registry={"fixture": SimpleNamespace(store=store)})
    reviewed = []

    def review(payload, **kwargs):
        reviewed.append(payload["candidate_uri"])
        return SimpleNamespace(visual_reviewed=False)

    monkeypatch.setattr("workers.workflow.storyboard.review_shot", review)
    state = {
        "script": storyboard(shot()),
        "keyframes": [
            {
                "shot_id": "S01",
                "uri": uri,
                "model": "fixture-image",
                "selected": True,
            }
        ],
    }
    result = prepare_gate("p1", state, skip=False, gateway=engine)
    assert result["shot_reviews"][0]["preview_status"] == "ready"
    assert result["shot_reviews"][0]["visual_reviewed"] is False
    assert reviewed and reviewed[0].startswith(str(project_path("p1")))
    client = TestClient(app, headers={"Authorization": f"Bearer {owner.token}"})
    url = "/v1/projects/p1/storyboard/S01/frame"
    response = client.get(url, headers={"Range": "bytes=0-15"})
    assert response.status_code == 206 and response.content == png[:16]
    stranger = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert stranger.get(url, headers={"Range": "bytes=0-15"}).status_code == 404
    assert TestClient(app).get(url).status_code == 401
    assert (
        materialize_project_asset("p1", "oss://foreign/keyframes/frame.png", gateway=engine) is None
    )
    assert (
        materialize_project_asset(
            "p2", str(project_path("p1") / "storyboard/S01/frame.png"), gateway=engine
        )
        is None
    )
    assert materialize_project_asset("p1", "https://127.0.0.1/secret.png", gateway=engine) is None


def test_user_node_object_candidate_gets_authenticated_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    owner = open_session()
    init_project("p1", status="draft", enterprise_id=owner.enterprise_id)
    store = MemoryObjectStore()
    png = _image()
    uri = store.put("image/generated.png", png, "image/png")
    engine = SimpleNamespace(
        registry={"fixture": SimpleNamespace(store=store)},
        generate_image=lambda *args, **kwargs: {"uri": uri, "model": "fixture-image"},
    )
    monkeypatch.setattr("gateway.get_gateway", lambda: engine)
    client = TestClient(app, headers={"Authorization": f"Bearer {owner.token}"})
    made = client.post(
        "/v1/projects/p1/canvas/nodes",
        json={
            "kind": "image",
            "position": {"x": 0, "y": 0},
            "data": {"prompt": "产品图"},
        },
    )
    assert made.status_code == 200
    generated = client.post(f"/v1/projects/p1/canvas/nodes/{made.json()['id']}/generate", json={})
    assert generated.status_code == 200, generated.text
    node = next(
        item for item in generated.json()["canvas"]["nodes"] if item["id"] == made.json()["id"]
    )
    url = node["data"]["thumbnail_url"]
    assert url.startswith("/v1/projects/p1/expert/media/")
    response = client.get(url, headers={"Range": "bytes=0-15"})
    assert response.status_code == 206 and response.content == png[:16]
    assert response.headers["cache-control"] == "private, no-store"
    stranger = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert stranger.get(url).status_code == 404
    init_project("p2", status="draft", enterprise_id=owner.enterprise_id)
    assert client.get(url.replace("/p1/", "/p2/")).status_code == 404
    assert client.get(url, headers={"Range": f"bytes={len(png) + 1}-"}).status_code == 416
