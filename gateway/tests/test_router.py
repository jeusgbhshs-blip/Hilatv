import pytest

from gateway.adapters.base import ModelRequest
from gateway.router import route


def test_mock_returns_structured_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HILATV_LIVE", raising=False)
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    response = route(ModelRequest(task="llm", prompt="hello"))
    body = response.model_dump()
    assert body["provider"] == "mock"
    assert body["ok"] is True
    assert body["cost_cny"] == 0
    assert body["output"]["echo"] == "hello"
    assert body["output"]["mock"] is True


def test_live_flag_with_zero_budget_stays_on_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    response = route(ModelRequest(task="image", prompt="product"))
    assert response.provider == "mock"
    assert response.cost_cny == 0


def test_live_flag_with_budget_has_no_adapter_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "10")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "1")
    with pytest.raises(RuntimeError, match="T03"):
        route(ModelRequest(task="tts", prompt="voice"))
