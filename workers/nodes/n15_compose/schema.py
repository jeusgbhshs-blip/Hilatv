"""N15 envelopes. The timeline is the replayable edit decision."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from workers.nodes.n06_voiceover.schema import ShotVoiceover
from workers.nodes.n13_subtitle.schema import SubtitleCue
from workers.nodes.n14_packaging.schema import PackageElement
from workers.schemas.asset import Candidate
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


class AudioTrack(BaseModel):
    """Optional soundtrack from N12. Empty source or license blocks delivery."""

    path: str = Field(min_length=1)
    start_s: float | None = None
    duration_s: float = Field(gt=0)
    source: str = ""
    license: str = ""


class TrackLicense(BaseModel):
    """One row of N12's licensing summary. Extra keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    source: str = ""
    license: str = ""
    kind: str = ""


class MotionCard(BaseModel):
    """Render-layer text for one slice of a shot. Times are relative to the shot."""

    text: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    y_ratio: float = Field(default=0.62, ge=0, le=1)


class ShotClip(BaseModel):
    """A real picture for one shot. N15 fits it; it does not paint a color plate."""

    shot_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    cards: list[MotionCard] = Field(default_factory=list)


class N15Input(BaseModel):
    script: Script
    # N12's beat-aligned storyboard. When present, picture, subtitles, and
    # packaging move onto those shot durations. The stored storyboard is unchanged.
    aligned_script: Script | None = None
    voiceovers: list[ShotVoiceover] = Field(default_factory=list)
    cues: list[SubtitleCue] = Field(default_factory=list)
    elements: list[PackageElement] = Field(default_factory=list)
    videos: list[Candidate] = Field(default_factory=list)
    brand_kit: BrandKit | None = None
    brief: Brief | None = None
    intro_s: float = Field(default=0, ge=0)
    outro_s: float = Field(default=0, ge=0)
    width: int | None = Field(default=None, ge=16)
    height: int | None = Field(default=None, ge=16)
    work_dir: str | None = None
    audio_track: AudioTrack | None = None
    licenses: list[TrackLicense] = Field(default_factory=list)
    shot_clips: list[ShotClip] = Field(default_factory=list)


class VideoClip(BaseModel):
    clip_id: str
    path: str
    duration_s: float
    start_s: float
    transition_out: str = "cut"
    grade_rr: float = 1
    grade_gg: float = 1
    grade_bb: float = 1
    # Mock-only stand-in. Live compose refuses this instead of painting a color plate.
    placeholder: bool = False


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
    produce_ids: dict[str, str] = Field(default_factory=dict)
