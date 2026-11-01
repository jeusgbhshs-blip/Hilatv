"""Real HTTP media bytes are separate from server-verified release permission.

The shared readiness fixture renders a real MP4 and records simulated verifier
results; it does not claim commercial VLM/speech quality. No model API is called.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.deliveries import _write
from app.main import app
from workers.identity.session import mint_session_for_tests, open_session
from workers.workflow.store import project_path, record_human_release, save_node, update_snapshot
from workers.workflow.tests import test_readiness as verifier_fixtures
from workers.workflow.tests.test_readiness import OWNER, attest
from workers.workflow.versions import list_versions

film_bytes = verifier_fixtures.film_bytes
prepared = verifier_fixtures.prepared


def _client():
    identity = mint_session_for_tests(OWNER)
    return TestClient(app, headers={"Authorization": f"Bearer {identity.token}"}), identity


def _export(prepared):
    snapshot, _state, path, _review, _proofs = prepared
    project_id = snapshot["project_id"]
    exported = project_path(project_id) / "deliveries" / "vertical.mp4"
    exported.parent.mkdir()
    exported.write_bytes(path.read_bytes() + b"different-unreviewed-export")
    row = {
        "version_id": "vertical",
        "aspect_ratio": "9:16",
        "language": "zh",
        "width": 320,
        "height": 180,
        "duration_s": 0.4,
        "modes": {},
        "qa_status": "pass",
        "quality_pass": True,
        "delivery_status": "ready",
    }
    _write(project_id, {"versions": [row], "files": {"vertical": str(exported)}, "shares": {}})
    return exported


@pytest.mark.parametrize("provenance", ["mock", "mixed", "unknown", "live"])
def test_completed_is_preview_without_exact_review_and_formal_route_never_leaks_bytes(
    prepared, provenance
):
    snapshot, state, path, _review, _proofs = prepared
    state = {**state, "media_provenance": provenance, "audio_provenance": provenance}
    save_node(snapshot["project_id"], "n15_compose", state)
    update_snapshot(
        snapshot["project_id"], quality_pass=True, delivery_status="ready", human_release=True
    )
    client, _identity = _client()
    url = f"/v1/projects/{snapshot['project_id']}"
    public = client.get(url)
    assert public.status_code == 200
    body = public.json()
    assert body["status"] == "completed" and body["quality_pass"] is False
    assert body["delivery_status"] != "ready"
    assert body["preview_available"] and body["preview_path"] == f"{url}/preview"
    assert body["deliverable"] is None and body["download_path"] is None
    assert "media_path" not in body and str(path.parent) not in public.text
    preview = client.get(body["preview_path"])
    assert preview.status_code == 200 and preview.content == path.read_bytes()
    assert preview.headers["content-disposition"].startswith("inline")
    assert preview.headers["cache-control"] == "private, no-store"
    for headers in ({}, {"Range": "bytes=0-31"}):
        denied = client.get(f"{url}/download", headers=headers)
        assert denied.status_code == 409 and denied.json()["detail"]["code"] == "delivery_not_ready"
        assert not denied.content.startswith(path.read_bytes()[:8])
        assert str(path) not in denied.text


def test_preview_requires_owner_and_serves_real_ranges_with_query_session(prepared):
    snapshot, _state, path, _review, _proofs = prepared
    client, identity = _client()
    url = f"/v1/projects/{snapshot['project_id']}/preview"
    assert TestClient(app).get(url).status_code == 401
    other = open_session()
    outsider = TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
    assert outsider.get(url).status_code == 404
    assert TestClient(app).get(url, params={"session": other.token}).status_code == 404
    response = TestClient(app).get(
        url, params={"session": identity.token}, headers={"Range": "bytes=7-35"}
    )
    assert response.status_code == 206
    assert response.content == path.read_bytes()[7:36]
    assert response.headers["content-range"] == f"bytes 7-35/{path.stat().st_size}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    head = client.head(url)
    assert head.status_code == 200 and head.content == b""
    assert int(head.headers["content-length"]) == path.stat().st_size
    assert client.get(url, headers={"Range": "bytes=999999999-"}).status_code == 416


def test_ready_formal_download_requires_exact_server_evidence(prepared):
    attest(prepared)
    snapshot, _state, path, _review, _proofs = prepared
    client, _identity = _client()
    response = client.get(f"/v1/projects/{snapshot['project_id']}/download")
    assert response.status_code == 200 and response.content == path.read_bytes()
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["etag"] == f'"{hashlib.sha256(response.content).hexdigest()}"'
    chunk = client.get(
        f"/v1/projects/{snapshot['project_id']}/download", headers={"Range": "bytes=0-15"}
    )
    assert chunk.status_code == 206 and chunk.content == path.read_bytes()[:16]
    assert TestClient(app).get(f"/v1/projects/{snapshot['project_id']}/download").status_code == 401


def test_human_release_does_not_create_formal_download_permission(prepared):
    attest(prepared)
    snapshot, _state, path, _review, _proofs = prepared
    update_snapshot(
        snapshot["project_id"],
        status="needs_human_review",
        deliverable=None,
        held_deliverable=str(path),
    )
    record_human_release(snapshot["project_id"], releaser="test-reviewer")
    client, _identity = _client()
    assert client.get(f"/v1/projects/{snapshot['project_id']}/preview").status_code == 200
    denied = client.get(f"/v1/projects/{snapshot['project_id']}/download")
    assert denied.status_code == 409
    assert "review_required_after_release" in {
        row["code"] for row in denied.json()["detail"]["reasons"]
    }


def test_archived_version_preview_and_download_use_that_versions_state(prepared):
    attest(prepared)
    snapshot, _state, path, _review, _proofs = prepared
    version = list_versions(snapshot["project_id"])["versions"][0]
    client, identity = _client()
    url = f"/v1/projects/{snapshot['project_id']}/versions/{version['version_id']}"
    assert TestClient(app).get(f"{url}/preview").status_code == 401
    preview = TestClient(app).get(
        f"{url}/preview", params={"session": identity.token}, headers={"Range": "bytes=0-15"}
    )
    assert preview.status_code == 206 and preview.content == path.read_bytes()[:16]
    assert client.get(f"{url}/download").status_code == 200
    update_snapshot(snapshot["project_id"], concept_degraded=True, revision_incomplete=True)
    assert (
        client.get(f"{url}/download").status_code == 200
    )  # Historical intent stays version-scoped.
    other = open_session()
    assert (
        TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
        .get(f"{url}/preview")
        .status_code
        == 404
    )


def test_export_qa_and_master_review_do_not_release_a_different_file(prepared):
    attest(prepared)
    snapshot = prepared[0]
    exported = _export(prepared)
    client, _identity = _client()
    rows = client.get(f"/v1/projects/{snapshot['project_id']}/versions").json()["versions"]
    assert rows[0]["qa_status"] == "pass" and rows[0]["quality_pass"] is False
    assert rows[0]["delivery_status"] == "needs_verification" and rows[0]["preview_available"]
    assert "media_path" not in rows[0] and str(exported) not in json.dumps(rows)
    preview = client.get(rows[0]["preview_path"])
    assert preview.status_code == 200 and preview.content == exported.read_bytes()
    chunk = client.get(rows[0]["preview_path"], headers={"Range": "bytes=16-48"})
    assert chunk.status_code == 206 and chunk.content == exported.read_bytes()[16:49]
    assert client.get(rows[0]["download_path"]).status_code == 409
    assert TestClient(app).get(rows[0]["preview_path"]).status_code == 401
    share = client.post(f"/v1/projects/{snapshot['project_id']}/versions/vertical/share")
    assert share.status_code == 200 and share.json()["download_allowed"] is False
    assert TestClient(app).get(share.json()["share_path"]).status_code == 409
    exported.write_bytes(exported.read_bytes() + b"newer-export")
    assert TestClient(app).get(share.json()["share_path"]).status_code == 410


def test_no_download_share_never_exposes_the_original_even_with_ranges(prepared, monkeypatch):
    attest(prepared)
    snapshot = prepared[0]
    client, _identity = _client()
    created = client.post(
        f"/v1/projects/{snapshot['project_id']}/shares", json={"role": "view_no_download"}
    )
    token = created.json()["token"]

    def forbidden(*_args):
        raise AssertionError("restricted shares must not even locate a raw candidate")

    monkeypatch.setattr("app.shares.media_file", forbidden)
    public = TestClient(app)
    metadata = public.get(f"/v1/share-links/{token}").json()
    assert metadata["download_allowed"] is False and metadata["shared_preview_available"] is False
    assert metadata["preview_path"] is None and metadata["preview_message"]
    assert "media_path" not in metadata
    for candidate in ("master", "deliverable", "private-candidate"):
        response = public.get(
            f"/v1/share-links/{token}/media/{candidate}", headers={"Range": "bytes=0-10"}
        )
        assert (
            response.status_code == 403
            and response.json()["detail"]["code"] == "restricted_preview_unavailable"
        )


def test_view_share_also_needs_exact_readiness_and_owner_transfer_revokes_it(prepared):
    snapshot, _state, path, _review, _proofs = prepared
    client, _identity = _client()
    token = client.post(
        f"/v1/projects/{snapshot['project_id']}/shares", json={"role": "view"}
    ).json()["token"]
    url = f"/v1/share-links/{token}/media/master"
    public = TestClient(app)
    assert public.get(url).status_code == 409
    attest(prepared)
    response = public.get(url)
    assert response.status_code == 200 and response.content == path.read_bytes()
    update_snapshot(snapshot["project_id"], enterprise_id=open_session().enterprise_id)
    assert public.get(url).status_code == 404


def test_changed_source_after_assessment_is_not_streamed_as_verified(prepared, monkeypatch):
    attest(prepared)
    snapshot, _state, path, _review, _proofs = prepared
    from app import delivery_gate

    real_pin = delivery_gate._pin_media

    def changed(project_id, source, digest):
        source.write_bytes(source.read_bytes() + b"changed-before-copy")
        return real_pin(project_id, source, digest)

    monkeypatch.setattr(delivery_gate, "_pin_media", changed)
    client, _identity = _client()
    assert client.get(f"/v1/projects/{snapshot['project_id']}/download").status_code == 409


def test_lazy_file_response_serves_pinned_verified_bytes_after_source_replacement(
    prepared, monkeypatch
):
    attest(prepared)
    snapshot, _state, path, _review, _proofs = prepared
    original = path.read_bytes()
    from app import delivery_gate

    real_response = delivery_gate.FileResponse

    def replace_after_pin(pinned, **kwargs):
        path.write_bytes(original + b"changed-after-pin")
        return real_response(pinned, **kwargs)

    monkeypatch.setattr(delivery_gate, "FileResponse", replace_after_pin)
    client, _identity = _client()
    response = client.get(f"/v1/projects/{snapshot['project_id']}/download")
    assert response.status_code == 200 and response.content == original
    assert client.get(f"/v1/projects/{snapshot['project_id']}/download").status_code == 409


def test_canvas_revision_is_public_without_submission_internals(prepared):
    snapshot = prepared[0]
    client, _identity = _client()
    original = client.get(f"/v1/projects/{snapshot['project_id']}/canvas").json()
    assert original["draft_revision"] is None
    assert original["master"]["ready"] is False and original["quality_pass"] is False
    update_snapshot(snapshot["project_id"], draft_revision=7, _submission={"secret": "not-public"})
    body = client.get(f"/v1/projects/{snapshot['project_id']}/canvas").json()
    assert body["draft_revision"] == 7 and "_submission" not in body
