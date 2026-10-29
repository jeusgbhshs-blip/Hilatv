"""N4 envelopes. The script itself is the chapter 5 model in ``workers.schemas``."""

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


class N4Input(BaseModel):
    """Brief plus an optional Brand Kit. Creative direction is T15, not this node."""

    brief: Brief
    brand_kit: BrandKit | None = None


class ScriptDraft(BaseModel):
    """Loose LLM draft. Empty defaults so the mock adapter adds no copy."""

    model_config = ConfigDict(extra="ignore")

    hook: str = ""
    selling_points: list[str] = Field(default_factory=list)
    proof: str = ""
    cta: str = ""
    notes: str = ""


class ScriptReview(BaseModel):
    """LLM self-check. Defaults pass so an empty mock does not block the rules."""

    model_config = ConfigDict(extra="ignore")

    passes: bool = True
    hook_in_first_3s: bool = True
    selling_points_from_brand: bool = True
    numbers_sourced: bool = True
    notes: str = ""
