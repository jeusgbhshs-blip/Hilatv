"""N18 envelopes. The change set is the chapter 5 RevisionDirective."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from workers.schemas.brand import BrandKit
from workers.schemas.director import RevisionDirective
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


class N18Input(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    script: Script
    brand_kit: BrandKit | None = None
    focused_shot_id: str | None = None


class RevisionPlan(BaseModel):
    """Which nodes rerun, and which shots need a new picture or a new length."""

    nodes: list[str]
    video_shots: list[str]
    reuse_shots: list[str]
    directive: RevisionDirective
