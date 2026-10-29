"""Route a model call to an adapter.

Live vendor adapters are registered in T03. Until then, a positive budget with
HILATV_LIVE=1 is an explicit error. A zero budget (the default, including CI)
always returns the mock adapter so the pipeline still yields structured JSON
and records a zero cost.
"""

from __future__ import annotations

import os

from gateway.adapters.base import ModelRequest, ModelResponse
from gateway.adapters.mock_adapter import MockAdapter


def budget_allows_live() -> bool:
    total = float(os.getenv("HILATV_BUDGET_CNY", "0") or 0)
    daily = float(os.getenv("HILATV_DAILY_BUDGET_CNY", "0") or 0)
    return total > 0 and daily > 0


def route(request: ModelRequest) -> ModelResponse:
    live = os.getenv("HILATV_LIVE", "0") == "1"
    if live and budget_allows_live():
        raise RuntimeError(
            "live model adapters are not registered yet (T03); "
            "unset HILATV_LIVE or keep both budgets at 0 to use the mock adapter"
        )
    return MockAdapter().invoke(request)
