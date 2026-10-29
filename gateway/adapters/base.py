"""Adapter protocol. Implementations live in this package only."""

from __future__ import annotations

from typing import Protocol

from gateway.models import AdapterResult, Invocation


class Adapter(Protocol):
    provider: str
    billable: bool
    tasks: frozenset[str]

    def available(self) -> bool: ...

    def invoke(self, call: Invocation) -> AdapterResult: ...
