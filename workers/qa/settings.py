"""Review thresholds and the project-wide retry cap.

The 7.5 pass line and the 3 reviews per shot stay fixed. They are SPEC
numbers. Everything here is an implementation knob T13 can share.
"""

from __future__ import annotations

import os

DEFORM_MIN_SIMILARITY = 0.90
FACE_MIN_SIMILARITY = 0.75
MIN_EDGE = 240
FLICKER_DELTA = 0.22
FLICKER_NEIGHBOR = 0.08
PROJECT_RETRIES = 12


def deform_min_similarity() -> float:
    return _float("HILATV_QA_DEFORM_MIN_SIMILARITY", DEFORM_MIN_SIMILARITY)


def face_min_similarity() -> float:
    return _float("HILATV_QA_FACE_MIN_SIMILARITY", FACE_MIN_SIMILARITY)


def min_edge() -> int:
    return _int("HILATV_QA_MIN_EDGE", MIN_EDGE)


def flicker_delta() -> float:
    return _float("HILATV_QA_FLICKER_DELTA", FLICKER_DELTA)


def flicker_neighbor() -> float:
    return _float("HILATV_QA_FLICKER_NEIGHBOR", FLICKER_NEIGHBOR)


def project_retry_cap() -> int:
    """Regenerate and switch-model decisions allowed for one project, all shots."""

    return _int("HILATV_QA_PROJECT_RETRIES", PROJECT_RETRIES)


class RetryBudget:
    """Shared counter. Each shot still stops after 3 reviews on its own."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = project_retry_cap() if limit is None else limit
        self.used = 0

    def allow(self) -> bool:
        return self.used < self.limit

    def consume(self) -> None:
        self.used += 1


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
