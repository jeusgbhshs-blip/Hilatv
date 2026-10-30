"""Review thresholds and the project-wide retry cap.

The 7.5 pass line and the 3 reviews per shot stay fixed. They are SPEC
numbers. Everything here is an implementation knob T13 can share.
Values are checked when a review starts. A bad value raises; it is not
replaced with the default.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

DEFORM_MIN_SIMILARITY = 0.90
FACE_MIN_SIMILARITY = 0.75
MIN_EDGE = 240
FLICKER_DELTA = 0.22
FLICKER_NEIGHBOR = 0.08
PROJECT_RETRIES = 12


class SettingsError(ValueError):
    """A QA threshold is missing a usable number or sits outside its range."""


def validate_settings() -> None:
    """Read every QA threshold. Call this when a review starts."""

    deform_min_similarity()
    face_min_similarity()
    min_edge()
    flicker_delta()
    flicker_neighbor()
    project_retry_cap()


def project_dir() -> Path:
    """Same root as the workflow store. Media must resolve inside it."""

    raw = os.getenv("HILATV_PROJECT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hilatv-projects").resolve()


def deform_min_similarity() -> float:
    return _similarity("HILATV_QA_DEFORM_MIN_SIMILARITY", DEFORM_MIN_SIMILARITY)


def face_min_similarity() -> float:
    return _similarity("HILATV_QA_FACE_MIN_SIMILARITY", FACE_MIN_SIMILARITY)


def min_edge() -> int:
    return _cap("HILATV_QA_MIN_EDGE", MIN_EDGE)


def flicker_delta() -> float:
    return _similarity("HILATV_QA_FLICKER_DELTA", FLICKER_DELTA)


def flicker_neighbor() -> float:
    return _similarity("HILATV_QA_FLICKER_NEIGHBOR", FLICKER_NEIGHBOR)


def project_retry_cap() -> int:
    """Regenerate and switch-model decisions allowed for one project, all shots."""

    return _cap("HILATV_QA_PROJECT_RETRIES", PROJECT_RETRIES)


class RetryBudget:
    """Shared counter. Each shot still stops after 3 reviews on its own.

    The in-memory object is what unit tests pass explicitly. A project run
    uses ``workers.qa.budget_store.ProjectBudget``, which writes this same
    counter to disk so every shot in the project shares it.
    """

    def __init__(self, limit: int | None = None) -> None:
        self.limit = project_retry_cap() if limit is None else limit
        self.used = 0

    def allow(self) -> bool:
        return self.used < self.limit

    def consume(self) -> None:
        self.used += 1


def _similarity(name: str, default: float) -> float:
    value = _number(name, default)
    if not math.isfinite(value) or not 0 < value <= 1:
        raise SettingsError(f"{name} must be in (0, 1], got {value}")
    return value


def _cap(name: str, default: int) -> int:
    value = _number(name, float(default))
    if not math.isfinite(value) or value < 1 or value != math.trunc(value):
        raise SettingsError(f"{name} must be an integer >= 1, got {value}")
    return int(value)


def _number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from exc
