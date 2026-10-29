"""Primary timeout or invalid JSON switches to the fallback adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, Field

from gateway.errors import GatewayError
from gateway.models import AdapterResult, Invocation
from gateway.schema_util import fill_json_schema
from gateway.tests.conftest import build_gateway

ROUTES = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: boom, model: boom-1}
    fallbacks:
      - {provider: steady, model: steady-1}
"""


class Brief(BaseModel):
    goal: str
    duration_s: int = Field(ge=1, le=600)


class Scripted:
    def __init__(self, provider: str, fn) -> None:  # type: ignore[no-untyped-def]
        self.provider = provider
        self.billable = True
        self.tasks = frozenset({"llm"})
        self.fn = fn
        self.calls = 0

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation) -> AdapterResult:
        self.calls += 1
        return self.fn(call)


def test_timeout_switches_to_fallback(tmp_path) -> None:
    def fail(call: Invocation) -> AdapterResult:
        raise TimeoutError("timeout")

    def ok(call: Invocation) -> AdapterResult:
        return AdapterResult(
            provider="steady",
            model=call.model,
            output={"text": "from-fallback"},
            cost_cny=Decimal("0.010000"),
        )

    boom = Scripted("boom", fail)
    steady = Scripted("steady", ok)
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"boom": boom, "steady": steady},
        limits=(True, Decimal("10"), Decimal("10")),
    )
    out = gateway.generate_text("hello", seed=1)
    assert out["text"] == "from-fallback"
    assert boom.calls == 1
    assert steady.calls == 1
    logs = gateway.store.list_logs()
    assert [row["status"] for row in logs] == ["error", "ok"]
    assert logs[0]["model"] == "boom-1"
    assert logs[1]["model"] == "steady-1"
    assert "timeout" in (logs[0]["error"] or "")
    gateway.generate_text("hello", seed=1)
    assert boom.calls == 1
    assert gateway.store.list_logs()[-1]["status"] == "cache_hit"


def test_invalid_schema_switches_to_fallback(tmp_path) -> None:
    def bad(call: Invocation) -> AdapterResult:
        return AdapterResult(
            provider="boom",
            model=call.model,
            output={"nope": True},
            cost_cny=Decimal("0"),
        )

    def good(call: Invocation) -> AdapterResult:
        assert call.json_schema is not None
        return AdapterResult(
            provider="steady",
            model=call.model,
            output=fill_json_schema(call.json_schema),
            cost_cny=Decimal("0.010000"),
        )

    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"boom": Scripted("boom", bad), "steady": Scripted("steady", good)},
        limits=(True, Decimal("10"), Decimal("10")),
    )
    out = gateway.generate_text("make a brief", schema=Brief, seed=2)
    Brief.model_validate(out)
    assert [row["status"] for row in gateway.store.list_logs()] == ["error", "ok"]


def test_all_adapters_fail_raises(tmp_path) -> None:
    def fail(call: Invocation) -> AdapterResult:
        raise TimeoutError("timeout")

    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"boom": Scripted("boom", fail), "steady": Scripted("steady", fail)},
        limits=(True, Decimal("10"), Decimal("10")),
    )
    with pytest.raises(GatewayError, match="all adapters failed"):
        gateway.generate_text("hello", seed=1)
    assert [row["status"] for row in gateway.store.list_logs()] == ["error", "error"]
