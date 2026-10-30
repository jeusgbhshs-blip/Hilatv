"""Pick a shorter cut without splitting a shot unless the hook itself is too long."""

from __future__ import annotations

from dataclasses import dataclass

from workers.schemas.script import Shot


@dataclass(frozen=True)
class KeptShot:
    shot: Shot
    source_start: float
    duration_s: float
    motion_s: float


def picture_length(shots: list[Shot]) -> float:
    return round(sum(float(shot.duration_s) for shot in shots), 3)


def keep_for_duration(shots: list[Shot], target_s: float) -> list[KeptShot]:
    """Keep whole shots that fit. A too-long hook is trimmed, not stretched."""

    starts: list[float] = []
    cursor = 0.0
    for shot in shots:
        starts.append(cursor)
        cursor += float(shot.duration_s)
    total = cursor
    if not shots:
        return []
    if target_s >= total - 0.05:
        return [
            KeptShot(shot, start, float(shot.duration_s), float(shot.duration_s))
            for shot, start in zip(shots, starts, strict=True)
        ]
    first = shots[0]
    if len(shots) == 1 or float(first.duration_s) >= target_s:
        span = min(float(first.duration_s), target_s)
        return [KeptShot(first, starts[0], span, float(first.duration_s))]
    last = shots[-1]
    if float(first.duration_s) + float(last.duration_s) > target_s:
        return [KeptShot(first, starts[0], target_s, float(first.duration_s))]
    chosen = [KeptShot(first, starts[0], float(first.duration_s), float(first.duration_s))]
    used = float(first.duration_s)
    for shot, start in zip(shots[1:-1], starts[1:-1], strict=True):
        if used + float(shot.duration_s) + float(last.duration_s) <= target_s + 1e-6:
            chosen.append(KeptShot(shot, start, float(shot.duration_s), float(shot.duration_s)))
            used += float(shot.duration_s)
    chosen.append(KeptShot(last, starts[-1], float(last.duration_s), float(last.duration_s)))
    return chosen


def duration_targets(
    *,
    requested: list[float] | None,
    brief_s: float,
    picture_s: float,
    platforms: list[str],
) -> list[float]:
    if requested:
        raw = [float(item) for item in requested]
    else:
        raw = [float(brief_s)]
        blob = " ".join(platforms).lower()
        short = any(name in blob for name in ("抖音", "tiktok", "视频号", "douyin"))
        if short and brief_s > 15:
            raw.append(15.0)
    found: list[float] = []
    for item in raw:
        value = picture_s if item >= picture_s - 0.05 else round(float(item), 3)
        if value > 0 and value not in found:
            found.append(value)
    return found or [picture_s]
