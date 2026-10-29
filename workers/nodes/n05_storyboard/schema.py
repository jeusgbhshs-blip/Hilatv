"""N5 envelopes. Shots are the chapter 5 model in ``workers.schemas``."""

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


class N5Input(BaseModel):
    brief: Brief
    script: Script
    brand_kit: BrandKit | None = None


class ShotHint(BaseModel):
    """Optional camera hint. Empty defaults so the mock plan adds nothing."""

    model_config = ConfigDict(extra="ignore")

    camera: str = ""
    shot_size: str = ""
    purpose: str = ""


class StoryboardHint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shots: list[ShotHint] = Field(default_factory=list)
    notes: str = ""
