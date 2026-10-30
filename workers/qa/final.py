"""N16 final review. The signature is reserved; T12 does not score a finished film."""

from __future__ import annotations

from typing import Any

from workers.schemas.asset import QAReport


def review_film(payload: dict[str, Any]) -> QAReport:
    del payload
    raise NotImplementedError("N16 final review is reserved and is not part of T12")
