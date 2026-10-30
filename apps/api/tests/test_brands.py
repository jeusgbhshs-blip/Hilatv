"""Brand admin and concept cards. No film workflow and no live model calls."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.projects import CreateProject, brand_for_request
from gateway import reset_gateway
from workers.brand_kit.tests.images import logo_png, noise_png, product_png

ENTERPRISE = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "gateway.sqlite"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    reset_gateway()
    return TestClient(app)


def _body(logo: bytes) -> dict:
    return {
        "enterprise_id": ENTERPRISE,
        "company_name": "青岛测试机械",
        "industry": "manufacturing",
        "logo_b64": base64.b64encode(logo).decode("ascii"),
        "phone": "0532-00001111",
        "website": "https://example.test",
        "products": [
            {
                "name": "测试泵 TP-1",
                "photo_b64": base64.b64encode(product_png()).decode("ascii"),
                "selling_points": ["压力 30MPa"],
            }
        ],
        "people": [
            {"role": "老板", "consent": False},
            {"role": "工程师", "consent": True},
        ],
    }


def test_saved_kit_is_reused_by_two_projects(client: TestClient) -> None:
    saved = client.post("/v1/brands", json=_body(logo_png()))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["previews"]["logo"].startswith("data:image/png;base64,")
    assert all(item["on_screen"] is False for item in body["anchors"])
    roles = [item["role"] for item in body["brand_kit"]["people"]]
    assert roles == ["工程师"]
    assert body["usable_people"] == [body["brand_kit"]["people"][0]["person_id"]]
    assert "老板" not in saved.text
    first = client.get(f"/v1/brands/{ENTERPRISE}")
    second = client.get(f"/v1/brands/{ENTERPRISE}")
    assert first.status_code == 200 and second.status_code == 200
    for key in ("logo", "colors", "fonts", "cta"):
        assert first.json()["brand_kit"][key] == second.json()["brand_kit"][key]
    points = first.json()["brand_kit"]["products"][0]["selling_points"]
    assert points == second.json()["brand_kit"]["products"][0]["selling_points"]
    request = CreateProject(sentence="再做一条", enterprise_id=ENTERPRISE)
    left = brand_for_request(request, project_id="p1")
    right = brand_for_request(request, project_id="p2")
    assert left["logo"] == right["logo"] == first.json()["brand_kit"]["logo"]
    assert left["colors"] == right["colors"]
    assert left["fonts"] == right["fonts"]
    assert left["cta"] == right["cta"]
    assert left["products"][0]["selling_points"] == points


def test_brand_id_without_enterprise_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/projects", json={"sentence": "做一条片", "brand_id": "brand-1"})
    assert response.status_code == 422
    assert "enterprise_id" in response.json()["detail"]


def test_bad_cutout_asks_for_another_picture(client: TestClient) -> None:
    response = client.post("/v1/brands", json=_body(noise_png()))
    assert response.status_code == 422
    assert "请更换图片" in response.json()["detail"]


def test_concepts_offer_three_cards_and_auto_choice(client: TestClient) -> None:
    response = client.post(
        "/v1/concepts",
        json={"sentence": "给测试泵做一条15秒宣传片，面向采购，风格稳重", "enterprise_id": None},
    )
    assert response.status_code == 200, response.text
    concept = response.json()["concept"]
    assert response.json()["brand_applied"] is False
    assert concept["selection"] == "你帮我选"
    assert len(concept["directions"]) == 3
