"""CNY price table for live calls. Rates live in pricing.yaml."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from gateway.money import money

_PACKAGE = Path(__file__).resolve().parent


class Pricing:
    def __init__(self, data: dict[str, Any]) -> None:
        self.default_output_tokens = int(data.get("default_output_tokens") or 512)
        self.default = _rates(data.get("default") or {})
        models = data.get("models") or {}
        self.models = {str(name): _rates(rates) for name, rates in models.items()}

    @classmethod
    def load(cls, path: Path | None = None) -> Pricing:
        target = path or _default_path()
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"pricing file must be a mapping: {target}")
        return cls(raw)

    def rates_for(self, model: str) -> tuple[Decimal, Decimal]:
        return self.models.get(model, self.default)

    def cost_for(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        input_rate, output_rate = self.rates_for(model)
        million = Decimal(1_000_000)
        total = Decimal(int(input_tokens)) * input_rate
        total += Decimal(int(output_tokens)) * output_rate
        return money(total / million)

    def estimate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> Decimal:
        import json

        schema_text = json.dumps(schema, ensure_ascii=False) if schema else ""
        tokens_in = _estimate_tokens(prompt) + _estimate_tokens(system or "")
        tokens_in += _estimate_tokens(schema_text)
        tokens_out = max_output_tokens or self.default_output_tokens
        return self.cost_for(model, tokens_in, tokens_out)

    def from_usage(self, model: str, usage: dict[str, Any]) -> Decimal:
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return self.cost_for(model, prompt_tokens, completion_tokens)


def _rates(raw: dict[str, Any]) -> tuple[Decimal, Decimal]:
    return (
        Decimal(str(raw.get("input_per_million", "0"))),
        Decimal(str(raw.get("output_per_million", "0"))),
    )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _default_path() -> Path:
    override = os.getenv("HILATV_PRICING_PATH", "").strip()
    if override:
        return Path(override)
    return _PACKAGE / "pricing.yaml"
