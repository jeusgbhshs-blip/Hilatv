"""N13 envelopes. The script, shots, and assets are chapter 5 models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from workers.nodes.n06_voiceover.schema import ShotVoiceover
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


class SubjectBox(BaseModel):
    """Normalized product box, origin at the top-left. The caller supplies it (no vision model)."""

    shot_id: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class N13Input(BaseModel):
    script: Script
    voiceovers: list[ShotVoiceover]
    brand_kit: BrandKit | None = None
    brief: Brief | None = None
    subject_boxes: list[SubjectBox] = Field(default_factory=list)
    width: int | None = Field(default=None, ge=16)
    height: int | None = Field(default=None, ge=16)
    work_dir: str | None = None


class HighlightSpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    color: str


class SubtitleCue(BaseModel):
    cue_id: str
    shot_id: str
    text: str
    lines: list[str]
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    audio_start_s: float = Field(ge=0)
    audio_end_s: float = Field(ge=0)
    alignment_error_ms: float = Field(ge=0)
    x_ratio: float
    y_ratio: float
    highlights: list[HighlightSpan] = Field(default_factory=list)
    language: str
