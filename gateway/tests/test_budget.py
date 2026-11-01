"""Total and daily CNY caps, alerts, and the Shanghai day reset."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, Field

from gateway.budget import limits_from_env
from gateway.clock import FrozenClock
from gateway.models import AdapterResult, Invocation
from gateway.tests.conftest import build_gateway

SH = ZoneInfo("Asia/Shanghai")

ROUTES = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: priced, model: deepseek-chat}
    fallbacks: []
"""


class Brief(BaseModel):
    goal: str
    duration_s: int = Field(ge=1, le=600)


class FlatPricing:
    def __init__(self, amount: str) -> None:
        self.amount = Decimal(amount)

    def estimate(self, model: str, prompt: str, **kwargs: object) -> Decimal:
        return self.amount

    def upper_bound(self, model: str, prompt: str, **kwargs: object) -> Decimal:
        return self.estimate(model, prompt, **kwargs)

    def from_usage(self, model: str, usage: dict) -> Decimal:  # type: ignore[type-arg]
        return self.amount


class Priced:
    def __init__(self, cost: str) -> None:
        self.provider = "priced"
        self.billable = True
        self.tasks = frozenset({"llm"})
        self.cost = Decimal(cost)
        self.calls = 0

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation) -> AdapterResult:
        self.calls += 1
        return AdapterResult(
            provider=self.provider,
            model=call.model,
            output={"text": f"live-{self.calls}"},
            cost_cny=self.cost,
        )


def _gw(tmp_path, *, clock, box, cost="0.040000"):  # type: ignore[no-untyped-def]
    adapter = Priced(cost)
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        clock=clock,
        pricing=FlatPricing(cost),
        box=box,
    )
    return gateway, adapter


def test_zero_budget_falls_back_to_mock_and_alerts(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 19, 49, tzinfo=SH))
    box = {"live": True, "total": Decimal("0"), "daily": Decimal("0")}
    gateway, adapter = _gw(tmp_path, clock=clock, box=box)
    out = gateway.generate_text("宣传片", schema=Brief, seed=1, project_id="p")
    Brief.model_validate(out)
    assert adapter.calls == 0
    logs = gateway.store.list_logs()
    assert logs[-1]["provider"] == "mock"
    assert logs[-1]["fallback_reason"] == "budget_exceeded"
    assert Decimal(logs[-1]["cost_cny"]) == 0
    alerts = gateway.store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "budget_exceeded"
    assert "budget_exceeded" in capsys.readouterr().out
    progress = (tmp_path / "progress.md").read_text(encoding="utf-8")
    assert "budget_exceeded" in progress
    assert "已花费" in progress
    gateway.generate_text("宣传片", schema=Brief, seed=2, project_id="p")
    assert len(gateway.store.list_alerts()) == 2
    assert (tmp_path / "progress.md").read_text(encoding="utf-8").count("budget_exceeded") == 1


def test_live_off_does_not_alert(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 12, 0, tzinfo=SH))
    gateway, adapter = _gw(
        tmp_path,
        clock=clock,
        box={"live": False, "total": Decimal("0"), "daily": Decimal("0")},
    )
    out = gateway.generate_text("hello", seed=1)
    assert out["mock"] is True
    assert adapter.calls == 0
    assert gateway.store.list_alerts() == []
    assert "budget_exceeded" not in capsys.readouterr().out


def test_daily_cap_resets_next_shanghai_day(tmp_path) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 23, 30, tzinfo=SH))
    box = {"live": True, "total": Decimal("10"), "daily": Decimal("0.05")}
    gateway, adapter = _gw(tmp_path, clock=clock, box=box)
    assert gateway.generate_text("a", seed=1)["text"] == "live-1"
    blocked = gateway.generate_text("b", seed=2)
    assert blocked["mock"] is True
    assert adapter.calls == 1
    assert gateway.store.list_alerts()[-1]["kind"] == "budget_exceeded"
    clock.set(datetime(2026, 10, 30, 0, 10, tzinfo=SH))
    assert gateway.generate_text("c", seed=3)["text"] == "live-2"
    assert adapter.calls == 2
    assert Decimal(gateway.store.sum_cost()) == Decimal("0.080000")
    assert Decimal(gateway.store.sum_cost(day="2026-10-30")) == Decimal("0.040000")


def test_total_cap_survives_the_day_until_raised(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 12, 0, tzinfo=SH))
    monkeypatch.setenv("HILATV_LIVE", "1")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0.05")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "10")
    adapter = Priced("0.040000")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        clock=clock,
        pricing=FlatPricing("0.040000"),
        limits=(True, Decimal("0.05"), Decimal("10")),
    )
    gateway.limits_fn = limits_from_env
    gateway.budget.limits_fn = limits_from_env
    assert gateway.generate_text("a", seed=1)["text"] == "live-1"
    assert gateway.generate_text("b", seed=2)["mock"] is True
    clock.set(datetime(2026, 10, 30, 8, 0, tzinfo=SH))
    assert gateway.generate_text("c", seed=3)["mock"] is True
    assert adapter.calls == 1
    monkeypatch.setenv("HILATV_BUDGET_CNY", "10")
    assert gateway.generate_text("d", seed=4)["text"] == "live-2"
    assert adapter.calls == 2


def test_budget_fallback_is_not_cached(tmp_path) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 12, 0, tzinfo=SH))
    box = {"live": True, "total": Decimal("0"), "daily": Decimal("1")}
    gateway, adapter = _gw(tmp_path, clock=clock, box=box)
    gateway.generate_text("same", seed=1)
    box["total"] = Decimal("10")
    assert gateway.generate_text("same", seed=1)["text"] == "live-1"
    assert adapter.calls == 1


def test_known_maximum_cost_blocks_underestimated_call_before_spend(tmp_path) -> None:
    clock = FrozenClock(datetime(2026, 10, 29, 12, 0, tzinfo=SH))

    class Underestimate(FlatPricing):
        def upper_bound(self, model: str, prompt: str, **kwargs: object) -> Decimal:
            return Decimal("1.000000")

        def from_usage(self, model: str, usage: dict) -> Decimal:  # type: ignore[type-arg]
            return Decimal("1.000000")

    class UsageAdapter(Priced):
        def invoke(self, call: Invocation) -> AdapterResult:
            self.calls += 1
            return AdapterResult(
                provider=self.provider,
                model=call.model,
                output={"text": "spent"},
                cost_cny=Decimal("0"),
                usage={"prompt_tokens": 10, "completion_tokens": 10},
            )

    adapter = UsageAdapter("0")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        clock=clock,
        pricing=Underestimate("0.010000"),
        box={"live": True, "total": Decimal("0.50"), "daily": Decimal("10")},
    )
    assert gateway.generate_text("a", seed=1)["mock"] is True
    assert Decimal(gateway.store.sum_cost()) == 0
    assert gateway.generate_text("b", seed=2)["mock"] is True
    assert adapter.calls == 0
