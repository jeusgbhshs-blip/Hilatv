"""N8 envelopes. Keyframe rows are chapter 5 Candidate models."""

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


class AnchorHint(BaseModel):
    """Text stand-in for an N7 anchor. A real anchor image is optional."""

    model_config = ConfigDict(extra="ignore")

    ref: str = ""
    description: str = ""
    uri: str | None = None


class N8Input(BaseModel):
    script: Script
    brief: Brief | None = None
    brand_kit: BrandKit | None = None
    scene_anchors: list[AnchorHint] = Field(default_factory=list)
    style_anchor: AnchorHint | None = None
    keyframe_candidates: int = Field(default=4, ge=3, le=8)
    enterprise_id: str | None = None
    prompt_suffix: str = ""
    reference_images: list[str] = Field(default_factory=list, max_length=14)
