"""N6 envelopes. Shots, assets, and the script are chapter 5 models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class N6Input(BaseModel):
    """A storyboard in, optional brand voice. Brief is carried through unchanged."""

    script: Script
    brand_kit: BrandKit | None = None
    brief: Brief | None = None


class WordStamp(BaseModel):
    """One TTS token. Chapter 5 Shot has no timestamp field, so N13 reads these."""

    model_config = ConfigDict(extra="ignore")

    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class ShotVoiceover(BaseModel):
    shot_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    speed: float = Field(gt=0)
    pause_s: float = Field(ge=0)
    audio_s: float = Field(gt=0)
    hold_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    timestamps: list[WordStamp]
    transcript: str
    cer: float = Field(ge=0)
    heard_check: str = ""
    loudness_dbfs: float
    clipped: bool
    lexicon: list[str] = Field(default_factory=list)
    role: str = Field(min_length=1)
