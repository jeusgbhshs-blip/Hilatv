"""In-repo music and sound-effect rows.

Every clip is synthesized in code for tests. Nothing here is a commercial
recording, and nothing is copied from another product.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

from workers.schemas.script import Shot

LICENSE = "CC0-1.0"
LICENSE_NOTE = (
    "Synthesized in this repository for tests and dedicated CC0. "
    "Not a third-party composition or a purchased library."
)


@dataclass(frozen=True)
class Track:
    library_id: str
    title: str
    bpm: float
    moods: tuple[str, ...]

    @property
    def source(self) -> str:
        return f"hilatv-test-library/{self.library_id}"


TRACKS: tuple[Track, ...] = (
    Track(
        "hilatv-self-made-steady",
        "Steady bed",
        90.0,
        ("低沉", "稳定", "稳重", "不煽情", "缓", "庄重", "留白", "克制"),
    ),
    Track(
        "hilatv-self-made-pulse",
        "Light pulse",
        120.0,
        ("轻快", "鼓点", "短句", "活泼"),
    ),
    Track(
        "hilatv-self-made-clear",
        "Clear bed",
        100.0,
        ("清楚", "平稳", "干净", "空间"),
    ),
)

SFX_CATALOG: dict[str, tuple[str, str]] = {
    "impact": ("产品落地", "hilatv-test-sfx/impact"),
    "machine": ("机械运转", "hilatv-test-sfx/machine"),
    "whoosh": ("转场", "hilatv-test-sfx/whoosh"),
}

_IMPACT = ("落地", "撞击", "冲击", "特写", "close_up")
_MACHINE = ("机械", "运转", "工厂", "车间", "装配", "机床")
_WHOOSH = ("转场", "dissolve", "xfade", "fade", "crossfade")


def select_track(mood: str) -> Track:
    text = mood or ""
    for track in TRACKS:
        if any(token in text for token in track.moods):
            return track
    return TRACKS[-1]


def match_sfx(shot: Shot) -> str | None:
    """One effect per shot, from the shot's own words and transition."""

    blob = " ".join(
        (
            shot.purpose,
            shot.visual,
            shot.scene_ref,
            shot.shot_size,
            shot.camera,
            shot.transition_out,
        )
    )
    if any(token in blob for token in _MACHINE):
        return "machine"
    if any(token in blob for token in _IMPACT):
        return "impact"
    transition = shot.transition_out.lower()
    if transition not in {"", "cut"} or any(token in blob for token in _WHOOSH):
        return "whoosh"
    return None


def render_sfx(kind: str, sample_rate: int = 48000) -> array.array:
    """A short self-made effect. Peak stays low so it does not own the mix."""

    if kind == "machine":
        frames = int(0.45 * sample_rate)
        samples = array.array("h", [0] * frames)
        for index in range(frames):
            env = 1.0 - (index / frames)
            tone = math.sin(2 * math.pi * 70 * index / sample_rate)
            buzz = math.sin(2 * math.pi * 35 * index / sample_rate)
            samples[index] = int(1400 * env * (0.7 * tone + 0.3 * buzz))
        return samples
    if kind == "whoosh":
        frames = int(0.18 * sample_rate)
        samples = array.array("h", [0] * frames)
        state = 17
        for index in range(frames):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            noise = (state / 0x7FFFFFFF) * 2 - 1
            env = math.sin(math.pi * index / frames)
            samples[index] = int(1200 * env * noise)
        return samples
    frames = int(0.09 * sample_rate)
    samples = array.array("h", [0] * frames)
    for index in range(frames):
        env = (1.0 - index / frames) ** 2
        tone = math.sin(2 * math.pi * 140 * index / sample_rate)
        samples[index] = int(1800 * env * tone)
    return samples
