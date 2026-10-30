"""Snap shot boundaries onto a beat grid.

Cuts move onto beats. The beat clock does not move to the old cuts.
Each shot stays at least as long as its voiceover and its original duration.
"""

from __future__ import annotations

import math

from gateway.media_bytes import MUSIC_RATE, beat_sample_index
from workers.nodes.n12_music.library import Track


def boundaries_for(
    durations: list[float],
    minimums: list[float],
    track: Track,
    *,
    sample_rate: int = MUSIC_RATE,
) -> list[int]:
    """Beat indexes for the start of each shot, plus one past the last shot."""

    cursor = 0
    marks = [0]
    for duration, minimum in zip(durations, minimums, strict=True):
        count = _beats_needed(duration, minimum, track.bpm)
        while True:
            start = beat_sample_index(cursor, track.bpm, sample_rate)
            end = beat_sample_index(cursor + count, track.bpm, sample_rate)
            length = (end - start) / sample_rate
            floor = max(duration, minimum)
            if length + 1e-4 >= floor:
                break
            count += 1
        cursor += count
        marks.append(cursor)
    return marks


def _beats_needed(duration: float, minimum: float, bpm: float) -> int:
    period = 60.0 / bpm
    need = max(duration, minimum, period)
    return max(1, math.ceil((need - 1e-6) / period))
