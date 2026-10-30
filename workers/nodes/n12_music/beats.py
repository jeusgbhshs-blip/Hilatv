"""Beat onsets from the rendered bed.

A click is a one-sample jump away from the pad. The pad itself moves slowly,
so a fixed jump threshold does not depend on the beat list we planned.
"""

from __future__ import annotations

import array


def detect_onsets(samples: array.array, sample_rate: int, *, jump: int = 8000) -> list[float]:
    found: list[float] = []
    previous = 0
    refractory = int(0.1 * sample_rate)
    last = -refractory
    for index, sample in enumerate(samples):
        delta = abs(int(sample) - previous)
        previous = int(sample)
        if delta < jump or index - last < refractory:
            continue
        found.append(index / sample_rate)
        last = index
    return found


def max_error_ms(cuts_s: list[float], beats_s: list[float]) -> float:
    if not cuts_s:
        return 0.0
    if not beats_s:
        return 1_000_000.0
    worst = 0.0
    for cut in cuts_s:
        nearest = min(abs(cut - beat) for beat in beats_s)
        worst = max(worst, nearest)
    return worst * 1000.0
