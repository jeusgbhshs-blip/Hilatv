"""只读分享、项目复制与用量接口。"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import open_session
from workers.workflow.store import init_project

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _client(tmp_path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    init_project(
        "shared",
        sentence="给高压球阀做一条 15 秒宣传片",
        status="completed",
        enterprise_id=ident.enterprise_id,
    )
    return TestClient(app, headers={"Authorization": f"Bearer {ident.token}"}), ident.enterprise_id


def test_share_link_reads_without_login(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    made = client.post("/v1/projects/shared/shares", json={"role": "view_no_download"})
    assert made.status_code == 200, made.text
    token = made.json()["token"]
    # 未登录也能读
    public = TestClient(app)
    read = public.get(f"/v1/share-links/{token}")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["sentence"].startswith("给高压球阀")
    assert body["ai_label"] is True
    assert body["download_allowed"] is False
    assert public.get("/v1/share-links/not-a-token").status_code == 404
    # 撤销后立即失效
    assert client.delete(f"/v1/projects/shared/shares/{token}").status_code == 200
    assert public.get(f"/v1/share-links/{token}").status_code == 404


def test_project_copy_keeps_canvas(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    copied = client.post("/v1/projects/shared/copy")
    assert copied.status_code == 201, copied.text
    new_id = copied.json()["project_id"]
    snapshot = client.get(f"/v1/projects/{new_id}").json()
    assert snapshot["status"] == "draft"
    assert "副本" in snapshot["sentence"]
    assert client.get(f"/v1/projects/{new_id}/canvas").status_code == 200


def test_usage_reports_budget_per_project(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    body = client.get("/v1/usage").json()
    assert "budget" in body and "projects" in body
    assert any(row["project_id"] == "shared" for row in body["projects"])
    assert body["budget"]["used"] >= 0
