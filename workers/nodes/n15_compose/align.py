"""Move the N15 timeline onto N12's beat-aligned shot durations.

N13 and N14 run beside N12, so their cues and cards are still on the
storyboard clock. Picture cuts use the aligned durations. A subtitle keeps
its offset inside the shot, because the voice is not stretched. A card that
filled a shot still fills that shot. The outro and the corner logo move to
the new end of the picture.
"""

from __future__ import annotations

from workers.nodes.n13_subtitle.schema import SubtitleCue
from workers.nodes.n14_packaging.schema import PackageElement
from workers.nodes.n15_compose.qa import QAError
from workers.nodes.n15_compose.schema import N15Input
from workers.schemas.script import Shot

_EPS = 1e-4


def apply_aligned_script(payload: N15Input, *, intro_s: float) -> N15Input:
    """Return a payload whose script, cues, and packaging share one clock."""

    aligned = payload.aligned_script
    if aligned is None:
        return payload
    source = payload.script
    if [shot.shot_id for shot in source.shots] != [shot.shot_id for shot in aligned.shots]:
        raise QAError(
            "aligned storyboard shots do not match the timeline",
            retryable=False,
        )
    old = _spans(source.shots)
    new = _spans(aligned.shots)
    cues = [_move_cue(cue, old, new) for cue in payload.cues]
    elements = [_move_element(item, intro_s, old, new) for item in payload.elements]
    return payload.model_copy(
        update={
            "script": aligned,
            "cues": cues,
            "elements": elements,
            "aligned_script": None,
        }
    )


def _spans(shots: list[Shot]) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    cursor = 0.0
    for shot in shots:
        duration = float(shot.duration_s)
        rows.append((cursor, cursor + duration))
        cursor += duration
    return rows


def _move_cue(
    cue: SubtitleCue,
    old: list[tuple[float, float]],
    new: list[tuple[float, float]],
) -> SubtitleCue:
    start = _voice_point(cue.start_s, old, new, bias="start")
    end = _voice_point(cue.end_s, old, new, bias="end")
    if end < start:
        end = start
    return cue.model_copy(update={"start_s": round(start, 3), "end_s": round(end, 3)})


def _move_element(
    element: PackageElement,
    intro_s: float,
    old: list[tuple[float, float]],
    new: list[tuple[float, float]],
) -> PackageElement:
    start = _package_point(element.start_s, intro_s, old, new, bias="start")
    end = _package_point(element.end_s, intro_s, old, new, bias="end")
    if end < start:
        end = start
    return element.model_copy(update={"start_s": round(start, 3), "end_s": round(end, 3)})


def _voice_point(
    time_s: float,
    old: list[tuple[float, float]],
    new: list[tuple[float, float]],
    *,
    bias: str,
) -> float:
    """Keep the voice's offset inside its shot. The line is not time-stretched."""

    if not old:
        return time_s
    if time_s > old[-1][1] + _EPS:
        return new[-1][1] + (time_s - old[-1][1])
    for index, (start, end) in enumerate(old):
        if not _owns(time_s, end, last=index == len(old) - 1, bias=bias):
            continue
        offset = max(0.0, time_s - start)
        room = new[index][1] - new[index][0]
        return new[index][0] + min(offset, max(0.0, room))
    return time_s


def _package_point(
    time_s: float,
    intro_s: float,
    old: list[tuple[float, float]],
    new: list[tuple[float, float]],
    *,
    bias: str,
) -> float:
    """Scale a card across its shot. Times past the picture slide with the outro."""

    if time_s <= intro_s + _EPS or not old:
        return time_s
    rel = time_s - intro_s
    old_end = old[-1][1]
    new_end = new[-1][1]
    if rel > old_end + _EPS:
        return intro_s + new_end + (rel - old_end)
    for index, (start, end) in enumerate(old):
        if not _owns(rel, end, last=index == len(old) - 1, bias=bias):
            continue
        span = end - start
        frac = 0.0 if span <= _EPS else min(1.0, max(0.0, (rel - start) / span))
        new_start, new_stop = new[index]
        return intro_s + new_start + frac * (new_stop - new_start)
    return intro_s + new_end


def _owns(time_s: float, end: float, *, last: bool, bias: str) -> bool:
    """A boundary belongs to the next shot for a start, and to this shot for an end."""

    if last:
        return True
    if bias == "end":
        return time_s <= end + _EPS
    return time_s < end - _EPS
