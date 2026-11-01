"""Concept previews stay with one owned, saved draft without starting a film."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import mint_session_for_tests
from workers.workflow.store import project_path, read_snapshot, update_snapshot


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_SESSION_SECRET", "draft-concept-tests")
    identity = mint_session_for_tests("33333333-3333-4333-8333-333333333333")
    client = TestClient(app, headers={"Authorization": f"Bearer {identity.token}"})
    response = client.post(
        "/v1/projects/drafts",
        json={
            "operation_id": str(uuid4()),
            "sentence": "为产品做15秒视频",
            "attachments": [{"kind": "url", "uri": "https://example.test/product"}],
        },
    )
    assert response.status_code == 201, response.text
    project = response.json()
    return client, project, identity


def fake_nodes(monkeypatch, captured, during_concept=None):
    def brief(body, **_kwargs):
        captured.append(body)
        return SimpleNamespace(payload={"brief": {}})

    def concept(body, **_kwargs):
        captured.append(body)
        if during_concept:
            during_concept()
        return SimpleNamespace(
            payload={
                "concept": {
                    "selection": "方向A",
                    "directions": [{"direction_id": "方向A", "title": "方向A", "idea": "测试"}],
                    "duration_s": 15,
                    "aspect_ratio": "9:16",
                }
            }
        )

    monkeypatch.setattr("app.brands.run_brief", brief)
    monkeypatch.setattr("app.brands.run_concept", concept)


def test_concept_reads_attachments_from_same_draft_and_keeps_owner(owned, monkeypatch):
    client, draft, identity = owned
    captured = []
    fake_nodes(monkeypatch, captured)
    response = client.post(
        "/v1/concepts",
        json={
            "project_id": draft["project_id"],
            "draft_revision": draft["draft_revision"],
            "sentence": "为产品做15秒视频",
        },
    )
    assert response.status_code == 200, response.text
    assert captured[0]["project_id"] == draft["project_id"]
    assert captured[0]["payload"]["attachments"][0]["uri"] == "https://example.test/product"
    snapshot = read_snapshot(draft["project_id"])
    assert snapshot["owner_member_id"] == identity.member_id
    assert snapshot["draft_revision"] == draft["draft_revision"]
    assert snapshot["status"] == "draft"
    assert snapshot["concept_preview"]["selection"] == "方向A"
    assert (project_path(draft["project_id"]) / "nodes/n03_concept.json").is_file()


def test_concept_never_overwrites_a_draft_changed_while_model_was_running(owned, monkeypatch):
    client, draft, _identity = owned
    fake_nodes(
        monkeypatch,
        [],
        lambda: update_snapshot(draft["project_id"], sentence="另一处的新修改", draft_revision=2),
    )
    response = client.post(
        "/v1/concepts",
        json={
            "project_id": draft["project_id"],
            "draft_revision": 1,
            "sentence": "为产品做15秒视频",
        },
    )
    assert response.status_code == 409
    assert "concept_preview" not in read_snapshot(draft["project_id"])
    assert not (project_path(draft["project_id"]) / "nodes/n03_concept.json").exists()


def test_invalid_or_foreign_concept_project_does_not_call_models(owned, monkeypatch):
    client, draft, _identity = owned
    captured = []
    fake_nodes(monkeypatch, captured)
    foreign = mint_session_for_tests("44444444-4444-4444-8444-444444444444")
    response = client.post(
        "/v1/concepts",
        headers={"Authorization": f"Bearer {foreign.token}"},
        json={
            "project_id": draft["project_id"],
            "draft_revision": 1,
            "sentence": "为产品做15秒视频",
        },
    )
    assert response.status_code == 404
    assert (
        client.post(
            "/v1/concepts",
            json={"project_id": "../escape", "draft_revision": 1, "sentence": "test"},
        ).status_code
        == 404
    )
    assert captured == []
