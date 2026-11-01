"""成员与交接。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import open_session


def _client(tmp_path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setenv("HILATV_MEMBER_DIR", str(tmp_path / "members"))
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    return TestClient(app, headers={"Authorization": f"Bearer {ident.token}"}), ident.member_id


def test_members_crud_and_handover(tmp_path, monkeypatch) -> None:
    client, self_id = _client(tmp_path, monkeypatch)
    listed = client.get("/v1/members").json()["members"]
    assert any(row["member_id"] == self_id and row["role"] == "owner" for row in listed)

    made = client.post("/v1/members", json={"name": "小王", "role": "editor"})
    assert made.status_code == 200, made.text
    target = made.json()["member_id"]
    assert made.json()["name"] == "小王"

    patched = client.patch(f"/v1/members/{target}", json={"role": "viewer"})
    assert patched.status_code == 200
    assert patched.json()["role"] == "viewer"

    # 建一个项目（负责人是自己），离职交接给自己→小王
    project_id = client.post("/v1/projects/blank", json={"sentence": "我要交接的项目"}).json()[
        "project_id"
    ]
    handover = client.post(f"/v1/members/{self_id}/handover", json={"to_member_id": target})
    assert handover.status_code == 200, handover.text
    assert handover.json()["projects_moved"] == 1
    snapshot = client.get(f"/v1/projects/{project_id}").json()
    assert snapshot.get("owner_member_id") == target

    assert client.delete(f"/v1/members/{target}").status_code == 200
    assert client.delete(f"/v1/members/{self_id}").status_code == 422
