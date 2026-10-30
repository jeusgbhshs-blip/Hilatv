"""N16 envelopes. Brief, script, brand, and the QA report stay on chapter 5."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.licensing import LicensingSummary
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


class N16Input(BaseModel):
    """One side of the compliance review. ``output`` also checks licences and files."""

    stage: Literal["input", "output"]
    brief: Brief | None = None
    script: Script | None = None
    brand_kit: BrandKit | None = None
    brand_archived: bool = False
    texts: list[str] = Field(default_factory=list)
    media_paths: list[str] = Field(default_factory=list)
    licensing: LicensingSummary | None = None
    instruction: str | None = None
