"""Cover a shot with the clean stretches of several candidates."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.qa.frames import SAMPLE_FPS
from workers.qa.pixels import shape_similarity
from workers.qa.settings import deform_min_similarity


@dataclass(frozen=True)
class Segment:
    candidate_id: str
    start_s: float
    end_s: float


def plan_splice(
    tracks: list[tuple[str, list[bool], list[Image.Image]]],
    *,
    fps: int = SAMPLE_FPS,
) -> list[Segment] | None:
    """Longest clean run, then the next, joined only when the frames match."""

    if not tracks or fps <= 0:
        return None
    usable: list[tuple[str, list[bool], list[Image.Image]]] = []
    for cid, flags, frames in tracks:
        limit = min(len(flags), len(frames))
        if limit <= 0:
            return None
        usable.append((cid, list(flags[:limit]), list(frames[:limit])))
    length = min(len(flags) for _cid, flags, _frames in usable)
    frames_for = {cid: frames for cid, _flags, frames in usable}
    tracks = usable
    pieces: list[tuple[str, int, int]] = []
    index = 0
    while index < length:
        options: list[tuple[int, str]] = []
        for cid, flags, _frames in tracks:
            if index >= len(flags) or not flags[index]:
                continue
            end = index
            while end < length and end < len(flags) and flags[end]:
                end += 1
            options.append((end - index, cid))
        if not options:
            return None
        options.sort(key=lambda item: (-item[0], item[1]))
        placed = False
        for _run, cid in options:
            end = index + _run
            if pieces:
                prev_id, _start, prev_end = pieces[-1]
                prev = frames_for[prev_id][prev_end - 1]
                nxt = frames_for[cid][index]
                if shape_similarity(prev, nxt) < deform_min_similarity():
                    continue
            pieces.append((cid, index, end))
            index = end
            placed = True
            break
        if not placed:
            return None
    merged: list[tuple[str, int, int]] = []
    for cid, start, end in pieces:
        if merged and merged[-1][0] == cid and merged[-1][2] == start:
            prev_id, prev_start, _prev_end = merged[-1]
            merged[-1] = (prev_id, prev_start, end)
        else:
            merged.append((cid, start, end))
    return [
        Segment(candidate_id=cid, start_s=start / fps, end_s=end / fps)
        for cid, start, end in merged
    ]
