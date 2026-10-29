"""Invocation and adapter result types shared by the router and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class Invocation:
    task: str
    prompt: str
    model: str
    provider: str
    system: str | None = None
    seed: int | None = None
    temperature: float | None = None
    timeout_s: float = 60.0
    json_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    negative_prompt: str | None = None
    project_id: str | None = None
    node: str | None = None
    shot_id: str | None = None
    attempt: int | None = None
    shot_type: str | None = None
    language: str | None = None


@dataclass
class AdapterResult:
    provider: str
    model: str
    output: dict[str, Any]
    cost_cny: Decimal
    usage: dict[str, int] = field(default_factory=dict)
