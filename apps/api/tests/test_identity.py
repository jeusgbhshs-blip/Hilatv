"""enterprise_id comes from the session. A foreign id does not read or write."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.projects import prepare_human_release
from workers.identity.session import mint_session_for_tests, open_session
from workers.workflow.store import init_project, project_path, read_events

_OTHER = "44444444-4444-4444-8444-444444444444"


def test_session_rejects_a_client_enterprise_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_SESSION_SECRET", "identity-test")
    client = TestClient(app)
    opened = client.post("/v1/session", json={})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["enterprise_id"] != _OTHER
    assert body["token"]
    rejected = client.post("/v1/session", json={"enterprise_id": _OTHER})
    assert rejected.status_code == 422
    assert "enterprise_id" in rejected.text
    queried = client.get("/health", params={"enterprise_id": _OTHER})
    assert queried.status_code == 422


def test_foreign_project_is_hidden_and_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_SESSION_SECRET", "identity-test")
    owner = open_session()
    other = mint_session_for_tests(_OTHER)
    init_project(
        "owned1",
        sentence="只有本企业能看见",
        status="completed",
        enterprise_id=owner.enterprise_id,
    )
    path = project_path("owned1") / "project.json"
    before = path.read_bytes()
    headers = {"Authorization": f"Bearer {other.token}"}
    client = TestClient(app)
    hidden = client.get("/v1/projects/owned1", headers=headers)
    assert hidden.status_code == 404
    assert "只有本企业能看见" not in hidden.text
    revised = client.post(
        "/v1/projects/owned1/revisions",
        headers=headers,
        json={"instruction": "改掉"},
    )
    assert revised.status_code == 404
    assert path.read_bytes() == before
    visible = client.get("/v1/projects/owned1", headers={"Authorization": f"Bearer {owner.token}"})
    assert visible.status_code == 200
    assert visible.json()["sentence"] == "只有本企业能看见"


def test_human_release_records_releaser(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_SESSION_SECRET", "identity-test")
    owner = open_session()
    other = open_session()
    init_project(
        "held1",
        sentence="待放行",
        status="needs_human_review",
        enterprise_id=owner.enterprise_id,
    )
    with pytest.raises(HTTPException) as raised:
        prepare_human_release("held1", other)
    assert raised.value.status_code == 404
    assert read_events("held1") == []
    prepare_human_release("held1", owner)
    events = read_events("held1")
    assert events[-1]["type"] == "human_review_released"
    assert events[-1]["releaser"] == owner.member_id
    assert events[-1]["enterprise_id"] == owner.enterprise_id
    assert isinstance(events[-1]["ts"], float)
    stored = json.loads((project_path("held1") / "project.json").read_text(encoding="utf-8"))
    assert stored["events"][-1]["releaser"] == owner.member_id
