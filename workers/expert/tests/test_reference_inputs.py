"""References survive upload authorization, graph generation and N8 envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from gateway.media_bytes import render_png
from workers.assets import store
from workers.expert.desk import add_edge, add_node, load_doc
from workers.expert.gates import GateError
from workers.expert.node_generate import generate_node
from workers.expert.uploads import materialize_attachments, materialize_reference, resolve_upload
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.node import run
from workers.nodes.n08_keyframe.tests.shots import request, shot
from workers.workflow.store import init_project


def _upload(root, owner, upload_id="a" * 32):
    folder = root / "uploads" / upload_id
    folder.mkdir(parents=True)
    (folder / ".enterprise").write_text(owner)
    (folder / "picture.png").write_bytes(render_png(2))
    return upload_id


class CaptureGateway:
    def __init__(self):
        self.images = []
        self.videos = []

    def generate_image(self, prompt, **kwargs):
        self.images.append(kwargs)
        return {"uri": "oss://hilatv/generated.png", "model": "mock-image"}

    def generate_video(self, prompt, **kwargs):
        self.videos.append(kwargs)
        return {"uri": "oss://hilatv/generated.mp4", "model": "mock-video", "duration_s": 4}


def test_graph_reference_is_actual_frozen_image_and_video_uses_selected_image(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    init_project("p1", status="draft", enterprise_id=ident.enterprise_id)
    upload_id = _upload(tmp_path, ident.enterprise_id)
    ref = add_node(
        "p1",
        {"kind": "ref_image", "position": {"x": 0, "y": 0}, "data": {"upload_id": upload_id}},
        enterprise_id=ident.enterprise_id,
    )
    image = add_node(
        "p1",
        {"kind": "image", "position": {"x": 1, "y": 0}, "data": {"prompt": "产品无文字"}},
        enterprise_id=ident.enterprise_id,
    )
    video = add_node(
        "p1",
        {"kind": "video", "position": {"x": 2, "y": 0}, "data": {"prompt": "推进"}},
        enterprise_id=ident.enterprise_id,
    )
    add_edge("p1", {"source": ref["id"], "target": image["id"], "role": "reference"})
    add_edge("p1", {"source": image["id"], "target": video["id"], "role": "reference"})
    engine = CaptureGateway()
    generate_node("p1", image["id"], gateway=engine)
    uri = engine.images[0]["params"]["reference_images"][0]
    path = Path(unquote(urlparse(uri).path))
    assert path.is_relative_to(tmp_path / "p1" / "media" / "inputs")
    assert path.read_bytes() == render_png(2)
    generate_node("p1", video["id"], gateway=engine)
    assert engine.videos[0]["params"]["image_url"] == "oss://hilatv/generated.png"
    assert engine.videos[0]["params"]["image_role"] == "first_frame"
    doc = load_doc("p1")
    assert all(
        row["verdict"] == "unreviewed"
        for node in doc.user_nodes
        for row in node.data.get("candidates", [])
    )


def test_authorization_rejects_foreign_upload_and_sibling_symlink(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    owner, stranger = open_session(), open_session()
    first = _upload(tmp_path, owner.enterprise_id)
    second = _upload(tmp_path, stranger.enterprise_id, "b" * 32)
    with pytest.raises(GateError):
        materialize_reference(first, enterprise_id=stranger.enterprise_id, project_id="p1")
    path = tmp_path / "uploads" / first / "picture.png"
    path.unlink()
    path.symlink_to(tmp_path / "uploads" / second / "picture.png")
    with pytest.raises(GateError):
        resolve_upload(first, enterprise_id=owner.enterprise_id)
    assert not (tmp_path / "p1" / "media").exists()


def test_attachment_helper_and_n8_pass_reference_in_typed_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    upload_id = _upload(tmp_path, ident.enterprise_id)
    references = materialize_attachments(
        [
            {"kind": "image", "upload_id": upload_id},
            {"kind": "pdf", "upload_id": "unused"},
        ],
        enterprise_id=ident.enterprise_id,
        project_id="proj-1",
    )
    engine = CaptureGateway()
    result = run(request(shot(), reference_images=references), gateway=engine)
    assert result.ok and len(engine.images) == 4
    assert all(call["params"]["reference_images"] == references for call in engine.images)
    assert all("data:image" not in json.dumps(call) for call in engine.images)


def test_asset_files_cannot_escape_through_symlink_or_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_ASSET_DIR", str(tmp_path))
    ident = open_session()
    meta = store.save_asset(ident.enterprise_id, "product_image", "p.png", render_png(1))
    folder = tmp_path / ident.enterprise_id / meta["asset_id"]
    (folder / "file.png").unlink()
    (folder / "file.png").symlink_to(tmp_path / "other-secret")
    assert store.asset_file(ident.enterprise_id, meta["asset_id"]) is None
    meta["suffix"] = "/../../../secret"
    (folder / "meta.json").write_text(json.dumps(meta))
    assert store.asset_file(ident.enterprise_id, meta["asset_id"]) is None
