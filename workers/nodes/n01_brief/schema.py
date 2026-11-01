"""N1 envelopes. The Brief itself is the chapter 5 model in ``workers.schemas``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from workers.schemas.brand import BrandKit
from workers.schemas.generation import GenerationSettings


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


class AttachmentRef(BaseModel):
    """A user-supplied file or page. Bytes stay out of the Brief."""

    kind: Literal["url", "pdf", "image"]
    uri: str = Field(min_length=1)
    filename: str | None = None


class N1Input(BaseModel):
    """What the caller hands N1. Brand Kit is read-only until T15 builds it."""

    raw_input: str = Field(min_length=1)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    brand_kit: BrandKit | None = None
    generation_settings: GenerationSettings = Field(default_factory=GenerationSettings)


class ExtractedBrief(BaseModel):
    """Loose LLM extraction. Empty means the model did not decide.

    Defaults are deliberate: the mock adapter fills defaults, so an unkeyed
    run contributes nothing and the industry table still produces a Brief.
    """

    model_config = ConfigDict(extra="ignore")

    industry: str = ""
    goal: str = ""
    platform: list[str] = Field(default_factory=list)
    duration_s: int | None = None
    aspect_ratios: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    video_type: str = ""
    audience: str = ""
    must_include: list[str] = Field(default_factory=list)
    style: str = ""


class ImageLabel(BaseModel):
    """Metadata-only image class. The picture bytes are not sent to a model."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["product", "logo", "person", "scene"] = "product"
    reason: str = ""
