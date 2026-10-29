from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings


def test_health_ok() -> None:
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "hilatv-api"
    assert body["env"] == "development"


def test_default_budget_blocks_live_spend() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.hilatv_live == 0
    assert settings.hilatv_budget_cny == 0
    assert settings.hilatv_daily_budget_cny == 0
