"""N16 final-review envelopes. Brief, script, and the QA report stay on chapter 5."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from workers.nodes.n12_music.schema import LicensingSummary
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


class ShotWindow(BaseModel):
    """One shot's span on the composed film, in seconds."""

    shot_id: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    anchor_uri: str | None = None
    expected_faces: int = Field(default=0, ge=0)
    model: str = ""

    @model_validator(mode="after")
    def end_after_start(self) -> ShotWindow:
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        return self


class N16FinalInput(BaseModel):
    """A composed film plus the chapter 5 records the review reads.

    ``enterprise_id`` is not a field. The node reads it from the project
    record. A copy in this payload is discarded before validation.
    """

    film_path: str = Field(min_length=1)
    shots: list[ShotWindow] = Field(min_length=1)
    brief: Brief
    script: Script
    brand_kit: BrandKit | None = None
    elements: list[dict[str, Any]] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)
    licensing: LicensingSummary | None = None
    reference_text: str | None = None
    instruction: str | None = None


class FilmIssue(BaseModel):
    shot_id: str | None = None
    code: str = Field(min_length=1)
    kind: Literal["hard_flaw", "brand", "compliance", "narrative", "hook", "review"]
    detail: str = Field(min_length=1)
