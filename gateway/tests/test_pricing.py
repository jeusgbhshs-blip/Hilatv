"""List-price math for live token usage."""

from __future__ import annotations

from decimal import Decimal

from gateway.pricing import Pricing


def test_deepseek_million_tokens_costs_ten_cny() -> None:
    pricing = Pricing.load()
    cost = pricing.from_usage(
        "deepseek-chat",
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
    )
    assert cost == Decimal("10.000000")


def test_unknown_model_uses_the_default_rate() -> None:
    pricing = Pricing.load()
    cost = pricing.estimate("some-new-model", "hello")
    assert cost > 0


def test_mock_model_is_free() -> None:
    pricing = Pricing.load()
    assert pricing.estimate("mock-llm", "hello") == 0
