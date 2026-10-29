"""Fit shot lengths to the Brief without cutting a line shorter than its audio.

Speech is whatever the TTS take measured. When that is shorter than the Brief,
the gap is picture hold (the line has already finished). When it is longer than
the Brief by more than 5%, a modest speed-up is tried first. Copy that is still
too long is flagged for N4.
"""

from __future__ import annotations

from workers.nodes.n06_voiceover.prosody import clamp_speed

# SPEC N5: total duration error ≤ 5%.
DURATION_TOLERANCE = 0.05
# Extra speed on top of the hook / CTA plan. 15% faster is still intelligible.
MAX_SPEED_BOOST = 1.15


def boost_factor(
    audio_s: list[float],
    pause_s: list[float],
    target_s: float,
    *,
    max_boost: float = MAX_SPEED_BOOST,
) -> float | None:
    """Speed multiplier that pulls a long read back toward ``target_s``.

    ``1.0`` means the take is already short enough. ``None`` means even the
    fastest allowed read stays more than 5% over the Brief.
    """

    if target_s <= 0:
        return None
    spoken = [max(0.0, audio - pause) for audio, pause in zip(audio_s, pause_s, strict=True)]
    spoken_sum = sum(spoken)
    pause_sum = sum(max(0.0, pause) for pause in pause_s)
    total = spoken_sum + pause_sum
    if total <= target_s * (1 + DURATION_TOLERANCE):
        return 1.0
    if pause_sum >= target_s * (1 + DURATION_TOLERANCE) or spoken_sum <= 0:
        return None
    needed = spoken_sum / (target_s - pause_sum)
    if needed <= 1:
        return 1.0
    if needed <= max_boost + 1e-9:
        return round(needed, 4)
    fastest = spoken_sum / max_boost + pause_sum
    if fastest <= target_s * (1 + DURATION_TOLERANCE):
        return max_boost
    return None


def boosted_speed(planned: float, factor: float) -> float:
    return clamp_speed(planned * factor)


def fit_durations(
    audio_s: list[float],
    *,
    target_s: float | None,
    reserved_s: float = 0.0,
) -> list[tuple[float, float, float]]:
    """Return ``(audio_s, hold_s, duration_s)`` for each spoken shot.

    ``reserved_s`` is time already used by shots that have no voiceover.
    Holds are whole milliseconds, shared in proportion to each line's audio,
    and the spoken shots plus the reserved time land on ``target_s``.
    """

    audio_ms = [int(round(max(0.0, item) * 1000)) for item in audio_s]
    if target_s is None:
        return [(ms / 1000, 0.0, ms / 1000) for ms in audio_ms]
    target_ms = int(round(target_s * 1000))
    reserved_ms = int(round(max(0.0, reserved_s) * 1000))
    goal_ms = target_ms - reserved_ms
    if goal_ms < 0:
        goal_ms = 0
    total_audio = sum(audio_ms)
    if total_audio >= goal_ms:
        return [(ms / 1000, 0.0, ms / 1000) for ms in audio_ms]
    gap = goal_ms - total_audio
    weights = [ms if ms > 0 else 1 for ms in audio_ms]
    weight_sum = sum(weights) or 1
    holds = [gap * weight // weight_sum for weight in weights]
    leftover = gap - sum(holds)
    order = sorted(range(len(holds)), key=lambda index: weights[index], reverse=True)
    for index in range(leftover):
        holds[order[index % len(holds)]] += 1
    fitted: list[tuple[float, float, float]] = []
    for audio, hold in zip(audio_ms, holds, strict=True):
        fitted.append((audio / 1000, hold / 1000, (audio + hold) / 1000))
    return fitted
