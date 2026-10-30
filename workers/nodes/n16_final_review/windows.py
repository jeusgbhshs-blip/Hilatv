"""Shot windows for N16 come from the composed timeline.

The storyboard still stores N6 durations. After N12, N15's clips are the
beat-aligned spans. Frame sampling has to use those spans, or a later shot
is scored on an earlier shot's pictures.
"""

from __future__ import annotations

from typing import Any

from workers.nodes.n16_final_review.schema import ShotWindow

_PACKAGING = frozenset({"intro", "outro"})


def windows_from_timeline(timeline: dict[str, Any]) -> list[ShotWindow]:
    """One window per shot clip. Intro and outro cards are not shots."""

    windows: list[ShotWindow] = []
    for clip in timeline.get("clips") or []:
        if not isinstance(clip, dict):
            continue
        shot_id = str(clip.get("clip_id") or "")
        if not shot_id or shot_id in _PACKAGING:
            continue
        start = float(clip.get("start_s") or 0)
        duration = float(clip.get("duration_s") or 0)
        if duration <= 0:
            continue
        windows.append(
            ShotWindow(
                shot_id=shot_id,
                start_s=round(start, 3),
                end_s=round(start + duration, 3),
            )
        )
    return windows


def apply_timeline_windows(shots: list[ShotWindow], timeline: dict[str, Any]) -> list[ShotWindow]:
    """Replace start and end with the timeline. Anchors and face counts stay."""

    aligned = windows_from_timeline(timeline)
    if not aligned:
        return list(shots)
    prior = {item.shot_id: item for item in shots}
    merged: list[ShotWindow] = []
    for window in aligned:
        old = prior.get(window.shot_id)
        if old is None:
            merged.append(window)
            continue
        merged.append(
            window.model_copy(
                update={
                    "anchor_uri": old.anchor_uri,
                    "expected_faces": old.expected_faces,
                    "model": old.model,
                }
            )
        )
    return merged
