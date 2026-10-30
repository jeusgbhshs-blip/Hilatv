"""N15 envelopes. The timeline is the replayable edit decision."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from workers.nodes.n06_voiceover.schema import ShotVoiceover
from workers.nodes.n13_subtitle.schema import SubtitleCue
from workers.nodes.n14_packaging.schema import PackageElement
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script


class NodeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    shot_id: str | None = None
    attempt: int = Field(default=1, ge=1, le=5)


class NodeResult(BaseModel):
    project_id: str
    node: str
    ok: bool
    payload: dict[str, Any]
    attempt: int


class N15Input(BaseModel):
    script: Script
    voiceovers: list[ShotVoiceover] = Field(default_factory=list)
    cues: list[SubtitleCue] = Field(default_factory=list)
    elements: list[PackageElement] = Field(default_factory=list)
    brand_kit: BrandKit | None = None
    brief: Brief | None = None
    intro_s: float = Field(default=0, ge=0)
    outro_s: float = Field(default=0, ge=0)
    width: int | None = Field(default=None, ge=16)
    height: int | None = Field(default=None, ge=16)
    work_dir: str | None = None


class VideoClip(BaseModel):
    clip_id: str
    path: str
    duration_s: float
    start_s: float
    transition_out: str = "cut"
    grade_rr: float = 1
    grade_gg: float = 1
    grade_bb: float = 1


class AudioClip(BaseModel):
    path: str
    start_s: float
    duration_s: float


class OverlayItem(BaseModel):
    kind: str
    path: str
    text: str = ""
    start_s: float
    end_s: float
    x: int = 0
    y: int = 0
    y_ratio: float = 0
    anchor: str = "topleft"
    animate: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)


class Timeline(BaseModel):
    width: int
    height: int
    fps: int = 30
    lut_path: str
    duration_s: float
    clips: list[VideoClip]
    audio: list[AudioClip]
    overlays: list[OverlayItem]
    work_dir: str
