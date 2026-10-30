"""Revision routes reject client paths and surface a degraded concept."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.projects import ReviseProject, project_revision
from workers.workflow.store import init_project, project_path, update_snapshot


def test_degraded_concept_is_public_and_paths_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project_id = "apirev01"
    init_project(project_id, sentence="一句", status="completed")
    update_snapshot(project_id, status="completed", sentence="一句")
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir()
    concept = {
        "concept": {
            "ok": False,
            "degraded": True,
            "text_source": "template_fallback",
            "directions": [{"source": "template_fallback"}],
        }
    }
    (nodes / "n03_concept.json").write_text(json.dumps(concept), encoding="utf-8")
    with TestClient(app) as client:
        status = client.get(f"/v1/projects/{project_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["concept_degraded"] is True
        assert body["concept_ok"] is False
        assert body["concept_text_source"] == "template_fallback"
        assert str(tmp_path) not in json.dumps(body)
        refused = client.post(
            f"/v1/projects/{project_id}/revisions",
            json={"instruction": "去掉 Logo", "path": str(tmp_path / "secret.mp4")},
        )
        assert refused.status_code == 422
        missing = client.post(f"/v1/projects/{project_id}/revisions/{'ab' * 16}/restore")
        assert missing.status_code == 404


def test_revision_route_uses_the_process_gateway(monkeypatch) -> None:
    sentinel = object()
    seen: dict[str, object] = {}

    def gateway() -> object:
        return sentinel

    def revise(
        project_id: str,
        instruction: str,
        *,
        shot_id: str | None = None,
        gateway: object = None,
    ) -> dict[str, object]:
        seen["gateway"] = gateway
        seen["project_id"] = project_id
        return {
            "project_id": project_id,
            "status": "needs_clarification",
            "question": "要改哪一个镜头？",
            "version_id": None,
        }

    monkeypatch.setattr("app.projects.get_gateway", gateway)
    monkeypatch.setattr("app.projects.revise_project", revise)
    body = project_revision("proj01", ReviseProject(instruction="嗯"))
    assert seen["gateway"] is sentinel
    assert body["version_id"] is None
    assert body["status"] == "needs_clarification"
