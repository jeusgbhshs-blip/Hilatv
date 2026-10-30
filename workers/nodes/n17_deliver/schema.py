"""N17 envelopes. Scripts, briefs, and assets stay on the chapter 5 models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

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


class SubjectTrack(BaseModel):
    """Normalized box on the 16:9 master. Optional end point moves in a straight line.

    T12 owns visual tracking. Until then the caller passes the box.
    """

    shot_id: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    x_end: float | None = Field(default=None, ge=0, le=1)
    y_end: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def box_stays_on_the_master(self) -> SubjectTrack:
        _inside(self.x, self.y, self.w, self.h)
        if self.x_end is not None or self.y_end is not None:
            _inside(
                self.x if self.x_end is None else self.x_end,
                self.y if self.y_end is None else self.y_end,
                self.w,
                self.h,
            )
        return self


class N17Input(BaseModel):
    """One 16:9 master, a Chinese storyboard, and the versions to export."""

    script: Script
    brief: Brief
    master_path: str = Field(min_length=1)
    brand_kit: BrandKit | None = None
    variants: list[Script] = Field(default_factory=list)
    subject_tracks: list[SubjectTrack] = Field(default_factory=list)
    aspect_ratios: list[str] = Field(default_factory=lambda: ["16:9", "9:16", "1:1"])
    languages: list[str] | None = None
    durations_s: list[float] | None = None
    long_edge: int | None = Field(default=None, ge=64, le=3840)
    regenerate_vertical: bool | None = None
    verify_pixels: bool = False
    work_dir: str | None = None
    audio_track: str | None = None


class GeometryRecord(BaseModel):
    shot_id: str
    mode: str
    src_w: int
    src_h: int
    out_w: int
    out_h: int
    crop_w: int
    crop_h: int
    subject0: list[float]
    subject1: list[float]
    start_s: float
    duration_s: float
    motion_s: float


class OverlayBox(BaseModel):
    kind: str
    text: str = ""
    language: str = ""
    x: int
    y: int
    w: int
    h: int
    start_s: float
    end_s: float


class SpokenLine(BaseModel):
    shot_id: str
    voiceover: str
    subtitle: str
    transcript: str = ""
    heard_check: str = "not_verified_in_mock"


class TrackSource(BaseModel):
    """Caller box, kept apart from the geometry the planner wrote."""

    shot_id: str
    provided: bool
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    x_end: float | None = None
    y_end: float | None = None


class DeliveryVersion(BaseModel):
    version_id: str
    aspect_ratio: str
    language: str
    duration_s: float
    width: int
    height: int
    path: str
    picture_path: str
    filters: str
    burn_filters: str
    geometry: list[GeometryRecord]
    overlays: list[OverlayBox]
    spoken: list[SpokenLine]
    tracks: list[TrackSource] = Field(default_factory=list)
    safe: dict[str, float]
    modes: dict[str, str]
    subject_box_source: str = "default"
    qa_status: str = "needs_review"


def _inside(x: float, y: float, w: float, h: float) -> None:
    if x + w > 1.0001 or y + h > 1.0001:
        raise ValueError("subject box must stay inside the master frame")
