"""Asset, Candidate, and QAReport (SPEC §5.4)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from workers.schemas.base import NODE_ID_PATTERN, JsonBool, JsonFloat, JsonInt, SchemaModel


class AssetKind(StrEnum):
    """Stored media. SPEC does not give an Asset sample; kinds follow N2/N7/N12/N17."""

    logo = "logo"
    product_photo = "product_photo"
    cutout = "cutout"
    person_photo = "person_photo"
    product_anchor = "product_anchor"
    person_anchor = "person_anchor"
    scene_anchor = "scene_anchor"
    style_anchor = "style_anchor"
    keyframe = "keyframe"
    video = "video"
    voiceover = "voiceover"
    music = "music"
    sound_effect = "sound_effect"
    subtitle = "subtitle"
    deliverable = "deliverable"


class QAScores(SchemaModel):
    """Five integer dimensions from the §5.4 sample, each 0–10."""

    product_fidelity: JsonInt = Field(ge=0, le=10)
    motion_quality: JsonInt = Field(ge=0, le=10)
    aesthetics: JsonInt = Field(ge=0, le=10)
    prompt_match: JsonInt = Field(ge=0, le=10)
    artifact_free: JsonInt = Field(ge=0, le=10)


class QAReport(SchemaModel):
    scores: QAScores
    hard_fail: list[str]
    total: JsonFloat = Field(ge=0, le=10)
    evaluator: str = Field(min_length=1)
    notes: str
    # True only after a vision judge scored a real frame. Absent in the SPEC
    # sample; default false so older JSON still loads. T18 reads this flag.
    visual_reviewed: JsonBool = False
    # How many judges returned a full score. degraded is the single-judge case.
    judges_used: JsonInt = Field(default=0, ge=0, le=2)
    degraded: JsonBool = False

    @field_validator("hard_fail")
    @classmethod
    def hard_fail_items(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item:
                raise ValueError("hard_fail items must be non-empty strings")
        return value


class Candidate(SchemaModel):
    candidate_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    node: str = Field(pattern=NODE_ID_PATTERN)
    model: str = Field(min_length=1)
    params: dict[str, Any]
    uri: str = Field(min_length=1)
    qa: QAReport
    selected: JsonBool


class Asset(SchemaModel):
    asset_id: str = Field(min_length=1)
    kind: AssetKind
    uri: str = Field(min_length=1)
    brand_id: str | None = None
    shot_id: str | None = None
    mime_type: str | None = None
    license_source: str | None = None
