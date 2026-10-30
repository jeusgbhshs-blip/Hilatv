"""Live content safety does not fall open onto the mock adapter."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gateway.errors import AdapterError, GatewayError
from gateway.models import AdapterResult, Invocation
from gateway.tests.conftest import build_gateway

_ROUTES = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: content-safety
    task: content_safety
    shot_type: "*"
    language: "*"
    primary: {provider: content_safety, model: content-security}
    fallbacks:
      - {provider: mock, model: mock-content-safety}
"""


class _Down:
    provider = "content_safety"
    billable = True
    tasks = frozenset({"content_safety"})

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation) -> AdapterResult:
        raise AdapterError("moderator down")


def test_live_without_a_moderator_does_not_use_mock(tmp_path) -> None:
    gateway = build_gateway(
        tmp_path,
        routes=_ROUTES,
        limits=(True, Decimal("10"), Decimal("10")),
    )
    with pytest.raises(GatewayError, match="unreviewed"):
        gateway.content_safety("普通介绍", params={"stage": "input"})


def test_live_adapter_error_does_not_use_mock(tmp_path) -> None:
    gateway = build_gateway(
        tmp_path,
        routes=_ROUTES,
        limits=(True, Decimal("10"), Decimal("10")),
        registry={"content_safety": _Down()},
    )
    with pytest.raises(GatewayError, match="all adapters failed"):
        gateway.content_safety("普通介绍", params={"stage": "input"})
    assert gateway.store.list_logs()[-1]["status"] == "error"
