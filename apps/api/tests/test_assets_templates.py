"""素材库与行业模板的 HTTP 覆盖。"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import open_session

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _client(tmp_path, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setenv("HILATV_ASSET_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    ident = open_session()
    return TestClient(app, headers={"Authorization": f"Bearer {ident.token}"}), ident.enterprise_id


def test_assets_are_per_enterprise(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    made = client.post(
        "/v1/assets",
        files={"file": ("product.png", PNG, "image/png")},
        data={"kind": "product_image"},
    )
    assert made.status_code == 200, made.text
    asset_id = made.json()["asset_id"]
    listed = client.get("/v1/assets").json()["assets"]
    assert [row["asset_id"] for row in listed] == [asset_id]
    assert client.get(f"/v1/assets/{asset_id}/file").status_code == 200
    stranger = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert stranger.get("/v1/assets").json()["assets"] == []
    assert stranger.get(f"/v1/assets/{asset_id}/file").status_code == 404
    assert client.delete(f"/v1/assets/{asset_id}").status_code == 200
    assert client.get("/v1/assets").json()["assets"] == []


def test_asset_kind_is_checked(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    bad = client.post(
        "/v1/assets",
        files={"file": ("clip.mp4", b"\x00\x00", "video/mp4")},
        data={"kind": "product_image"},
    )
    assert bad.status_code == 422


def test_templates_list_and_preview(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)
    rows = client.get("/v1/templates").json()["templates"]
    assert {row["template_id"] for row in rows} >= {"ecommerce", "manufacturing"}
    ecommerce = next(row for row in rows if row["template_id"] == "ecommerce")
    assert ecommerce["shot_count"] >= 3
    assert ecommerce["default_sentence"]
    preview = client.get("/v1/templates/ecommerce/canvas")
    assert preview.status_code == 200
    nodes = preview.json()["nodes"]
    assert any(node["kind"] == "shot" and node.get("placeholder") for node in nodes)


def test_template_apply_creates_a_project(tmp_path, monkeypatch) -> None:
    client, _enterprise = _client(tmp_path, monkeypatch)

    async def fake_start(**kwargs) -> str:
        assert kwargs["project_id"]
        assert kwargs["sentence"]
        return "wf-template"

    monkeypatch.setattr("app.templates.start_film", fake_start)
    made = client.post("/v1/templates/manufacturing/apply", json={"sentence": ""})
    assert made.status_code == 202, made.text
    assert made.json()["template_id"] == "manufacturing"
