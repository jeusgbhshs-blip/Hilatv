"""Snap shot boundaries onto a beat grid.

Cuts move onto beats. The beat clock does not move to the old cuts.
Each shot stays at least as long as its voiceover and its original duration.
"""

from __future__ import annotations

import math

from gateway.media_bytes import MUSIC_RATE, beat_sample_index
from workers.media.packaging import FPS
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


def target_boundaries(
    durations: list[float], minimums: list[float], track: Track, total_frames: int
) -> list[int]:
    """Fit beat cuts into an immutable end frame without trimming narration.

    A shortest-path search chooses the nearest feasible beat boundaries. Only
    picture holds may shrink; impossible speech/beat constraints fail explicitly.
    """

    if not durations or len(durations) != len(minimums):
        raise ValueError("beat alignment needs matching shot durations and audio minima")
    floors = [max(1, math.ceil(value * FPS - 1e-7)) for value in minimums]
    if sum(floors) > total_frames:
        raise ValueError("voiceover does not fit the target story duration")
    if len(durations) == 1:
        return [0, total_frames]
    period = 60.0 / track.bpm
    candidates = sorted(
        {
            round(beat * period * FPS)
            for beat in range(1, math.ceil(total_frames / FPS / period) + 1)
            if 0 < round(beat * period * FPS) < total_frames
        }
    )
    states: list[tuple[int, float, list[int]]] = [(0, 0.0, [0])]
    planned = 0.0
    original = sum(durations)
    for index in range(len(durations) - 1):
        planned += durations[index]
        desired = planned / original * total_frames
        room_after = sum(floors[index + 1 :])
        next_states = []
        cursor = 0
        best = None
        for frame in candidates:
            while cursor < len(states) and states[cursor][0] <= frame - floors[index]:
                if best is None or states[cursor][1] < best[1]:
                    best = states[cursor]
                cursor += 1
            if best is not None and frame <= total_frames - room_after:
                next_states.append((frame, best[1] + (frame - desired) ** 2, best[2] + [frame]))
        states = next_states
        if not states:
            raise ValueError("no beat-aligned edit fits the target without cutting narration")
    feasible = [row for row in states if total_frames - row[0] >= floors[-1]]
    if not feasible:
        raise ValueError("the last voiceover does not fit the target beat-aligned edit")
    return min(feasible, key=lambda row: row[1])[2] + [total_frames]
