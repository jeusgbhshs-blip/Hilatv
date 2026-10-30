"""N3 envelopes. Directions are node-local; Brief and BrandKit stay chapter 5."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief


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


class N3Input(BaseModel):
    brief: Brief
    brand_kit: BrandKit | None = None
    selection: str | None = None


class DirectionDraft(BaseModel):
    """Loose model output. Empty defaults so an unkeyed mock adds nothing."""

    model_config = ConfigDict(extra="ignore")

    direction_id: str = ""
    title: str = ""
    idea: str = ""
    mood: str = ""
    structure: list[str] = Field(default_factory=list)
    style_keywords: list[str] = Field(default_factory=list)
    estimated_effect: str = ""


class DraftSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    directions: list[DirectionDraft] = Field(default_factory=list)
