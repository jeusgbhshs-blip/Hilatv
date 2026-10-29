"""Script and Shot (SPEC §5.3). On-screen text is for the render layer only."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from workers.schemas.base import JsonFloat, JsonInt, SchemaModel


class GenerationMode(StrEnum):
    """How N5 asks a later node to produce the shot. SPEC §5.3."""

    text_to_video = "text_to_video"
    image_to_video = "image_to_video"
    first_last_frame = "first_last_frame"
    reference_to_video = "reference_to_video"
    product_composite = "product_composite"
    motion_graphics = "motion_graphics"


class ShotStatus(StrEnum):
    """Shot lifecycle. The SPEC sample uses ``pending``."""

    pending = "pending"
    generating = "generating"
    passed = "passed"
    rejected = "rejected"
    fallback = "fallback"


class ScriptSectionKind(StrEnum):
    """N4 narrative beats: hook, selling points, proof, CTA."""

    hook = "hook"
    selling_point = "selling_point"
    proof = "proof"
    cta = "cta"


class OnScreenText(SchemaModel):
    """Text the render layer (N13/N14/N15) composites. Models must not draw it."""

    text: str = Field(min_length=1)
    style: str = Field(min_length=1)
    in_: JsonFloat = Field(alias="in", ge=0)
    out: JsonFloat = Field(ge=0)

    @model_validator(mode="after")
    def out_not_before_in(self) -> Self:
        if self.out < self.in_:
            raise ValueError("on_screen_text.out must be greater than or equal to in")
        return self


class Shot(SchemaModel):
    shot_id: str = Field(min_length=1)
    order: JsonInt = Field(ge=1)
    duration_s: JsonFloat = Field(gt=0, le=180)
    purpose: str = Field(min_length=1)
    visual: str = Field(min_length=1)
    shot_size: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    subject_refs: list[str]
    scene_ref: str
    voiceover: str
    on_screen_text: list[OnScreenText]
    transition_out: str = Field(min_length=1)
    generation_mode: GenerationMode
    status: ShotStatus

    @field_validator("subject_refs")
    @classmethod
    def subject_ref_items(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item:
                raise ValueError("subject_refs must be non-empty strings")
        return value

    @model_validator(mode="after")
    def subject_or_scene(self) -> Self:
        if not self.subject_refs and not self.scene_ref:
            raise ValueError("shot needs a subject_refs entry or a scene_ref")
        return self


class ScriptSection(SchemaModel):
    kind: ScriptSectionKind
    text: str = Field(min_length=1)
    shot_ids: list[str] = Field(default_factory=list)


class Script(SchemaModel):
    """Ordered script. SPEC gives a Shot example and describes this shape in N4."""

    script_id: str = Field(min_length=1)
    brief_id: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=16)
    sections: list[ScriptSection] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)

    @model_validator(mode="after")
    def at_most_three_selling_points(self) -> Self:
        selling_points = [
            section for section in self.sections if section.kind is ScriptSectionKind.selling_point
        ]
        if len(selling_points) > 3:
            raise ValueError("a script has at most 3 selling points")
        return self
