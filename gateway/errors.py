"""Gateway errors. Budget fallback does not raise; exhausted adapters do."""

from __future__ import annotations


class GatewayError(RuntimeError):
    """A call could not be completed."""


class AdapterError(GatewayError):
    """A vendor or scripted adapter failed."""


class AdapterTimeout(AdapterError):
    """The adapter exceeded its timeout."""
