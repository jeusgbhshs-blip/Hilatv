"""N10 envelopes. Video rows are chapter 5 Candidate models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from workers.nodes.n08_keyframe.schema import AnchorHint
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


class N10Input(BaseModel):
    script: Script
    candidates: list[Candidate]
    brief: Brief | None = None
    brand_kit: BrandKit | None = None
    scene_anchors: list[AnchorHint] = Field(default_factory=list)
    style_anchor: AnchorHint | None = None
    video_candidates: int = Field(default=4, ge=3, le=8)
    enterprise_id: str | None = None
    brand_archived: bool = False
