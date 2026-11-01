"""Explicit whole-film frame budgets; missing targets keep legacy node timing."""

from __future__ import annotations

import math
from dataclasses import dataclass

from workers.media.packaging import FPS, outro_spec


@dataclass(frozen=True)
class DurationBudget:
    total_frames: int
    intro_frames: int
    body_frames: int
    outro_frames: int

    @property
    def total_s(self) -> float:
        return self.total_frames / FPS

    @property
    def intro_s(self) -> float:
        return self.intro_frames / FPS

    @property
    def body_s(self) -> float:
        return self.body_frames / FPS

    @property
    def outro_s(self) -> float:
        return self.outro_frames / FPS


def duration_budget(
    target_duration_s: float, *, intro_s: float = 0, outro_s: float | None = None
) -> DurationBudget:
    """Reserve real intro/outro before fitting speech or aligning body cuts."""

    ending = float(outro_spec()["duration_s"]) if outro_s is None else outro_s
    values = (target_duration_s, intro_s, ending)
    if any(isinstance(value, bool) or not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("duration budget values must be finite nonnegative seconds")
    total, opening, closing = (round(value * FPS) for value in values)
    if outro_s is None:
        closing = min(closing, max(0, total - opening - 4 * FPS))
    body = total - opening - closing
    if total <= 0 or body < 4 * FPS:
        raise ValueError(
            "target duration leaves no time for the minimum 4-second story after packaging"
        )
    return DurationBudget(total, opening, body, closing)


def allocate_frames(minimums_s: list[float], weights: list[float], total_frames: int) -> list[int]:
    """Share picture holds, never taking a frame that contains narration away."""

    if not minimums_s or len(minimums_s) != len(weights):
        raise ValueError("a duration budget needs matching shot minima and weights")
    minima = [max(1, math.ceil(value * FPS - 1e-7)) for value in minimums_s]
    room = total_frames - sum(minima)
    if room < 0:
        raise ValueError("voiceover does not fit the target duration; shorten the script")
    positive = [max(0.0, value) for value in weights]
    norm = sum(positive)
    positive = positive if norm > 0 else [1.0] * len(weights)
    norm = sum(positive)
    raw = [room * value / norm for value in positive]
    holds = [int(value) for value in raw]
    remaining = room - sum(holds)
    order = sorted(range(len(raw)), key=lambda index: raw[index] - holds[index], reverse=True)
    for index in order[:remaining]:
        holds[index] += 1
    return [minimum + hold for minimum, hold in zip(minima, holds, strict=True)]
