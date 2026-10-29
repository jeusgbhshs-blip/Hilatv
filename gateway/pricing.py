"""CNY price table for live calls. Rates live in pricing.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from gateway.money import money

_PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class RateCard:
    unit: str = "token"
    input_per_million: Decimal = Decimal("0")
    output_per_million: Decimal = Decimal("0")
    per_image: Decimal = Decimal("0")
    per_second: Decimal = Decimal("0")
    per_thousand_chars: Decimal = Decimal("0")
    default_seconds: int = 5


class Pricing:
    def __init__(self, data: dict[str, Any]) -> None:
        self.default_output_tokens = int(data.get("default_output_tokens") or 512)
        self.default = _card(data.get("default") or {})
        models = data.get("models") or {}
        self.models = {str(name): _card(rates) for name, rates in models.items()}
        tasks = data.get("task_defaults") or {}
        self.task_defaults = {str(name): _card(rates) for name, rates in tasks.items()}

    @classmethod
    def load(cls, path: Path | None = None) -> Pricing:
        target = path or _default_path()
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"pricing file must be a mapping: {target}")
        return cls(raw)

    def card_for(self, model: str, task: str | None = None) -> RateCard:
        if model in self.models:
            return self.models[model]
        if task and task in self.task_defaults:
            return self.task_defaults[task]
        return self.default

    def rates_for(self, model: str) -> tuple[Decimal, Decimal]:
        card = self.models.get(model, self.default)
        return card.input_per_million, card.output_per_million

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
        task: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Decimal:
        import json

        card = self.card_for(model, task)
        if card.unit == "image":
            count = int((params or {}).get("n") or 1)
            return money(card.per_image * Decimal(count))
        if card.unit == "second":
            raw = (params or {}).get("duration_s")
            seconds = card.default_seconds if raw is None else raw
            return money(card.per_second * Decimal(str(seconds)))
        if card.unit == "char":
            chars = max(1, len(prompt or ""))
            return money(card.per_thousand_chars * Decimal(chars) / Decimal(1000))
        schema_text = json.dumps(schema, ensure_ascii=False) if schema else ""
        tokens_in = _estimate_tokens(prompt) + _estimate_tokens(system or "")
        tokens_in += _estimate_tokens(schema_text)
        tokens_out = max_output_tokens or self.default_output_tokens
        return self.cost_for(model, tokens_in, tokens_out)

    def from_usage(self, model: str, usage: dict[str, Any]) -> Decimal:
        card = self.models.get(model)
        if card is not None and card.unit == "image":
            count = int(usage.get("images") or 1)
            return money(card.per_image * Decimal(count))
        if card is not None and card.unit == "second":
            seconds = usage.get("video_seconds")
            if seconds is None:
                seconds = card.default_seconds
            return money(card.per_second * Decimal(str(seconds)))
        if card is not None and card.unit == "char":
            chars = int(usage.get("characters") or 0)
            return money(card.per_thousand_chars * Decimal(chars) / Decimal(1000))
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return self.cost_for(model, prompt_tokens, completion_tokens)


def _card(raw: dict[str, Any] | None) -> RateCard:
    body = raw or {}
    return RateCard(
        unit=str(body.get("unit") or "token"),
        input_per_million=Decimal(str(body.get("input_per_million", "0"))),
        output_per_million=Decimal(str(body.get("output_per_million", "0"))),
        per_image=Decimal(str(body.get("per_image", "0"))),
        per_second=Decimal(str(body.get("per_second", "0"))),
        per_thousand_chars=Decimal(str(body.get("per_thousand_chars", "0"))),
        default_seconds=int(body.get("default_seconds") or 5),
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
