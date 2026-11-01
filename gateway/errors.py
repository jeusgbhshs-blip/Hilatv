"""Gateway errors. Budget fallback does not raise; exhausted adapters do."""

from __future__ import annotations

from gateway.models import AdapterResult


class GatewayError(RuntimeError):
    """A call could not be completed."""


class AdapterError(GatewayError):
    """A vendor or scripted adapter failed."""


class AdapterTimeout(AdapterError):
    """The adapter exceeded its timeout."""


class StorageError(GatewayError):
    """Object storage rejected a put or get."""


class BillableAdapterError(AdapterError):
    """Provider completed; local parsing/download/storage failed after it incurred cost."""

    def __init__(self, message: str, result: AdapterResult) -> None:
        super().__init__(message)
        self.result = result
