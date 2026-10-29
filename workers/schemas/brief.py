"""Brief (SPEC §5.2) plus the N1 clarifying-question shape."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from workers.schemas.base import (
    ASPECT_RATIO_PATTERN,
    LANGUAGE_PATTERN,
    JsonInt,
    SchemaModel,
)


class ClarifyingQuestion(SchemaModel):
    """One N1 follow-up. Each question carries a recommended default."""

    question: str = Field(min_length=1)
    recommended: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)


class Brief(SchemaModel):
    brief_id: str = Field(min_length=1)
    raw_input: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    platform: list[str] = Field(min_length=1)
    duration_s: JsonInt = Field(ge=5, le=180)
    aspect_ratios: list[str] = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    video_type: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    must_include: list[str]
    style: str = Field(min_length=1)
    assumptions: list[str]
    open_questions: list[ClarifyingQuestion] = Field(default_factory=list)

    @field_validator("platform", "must_include", "assumptions")
    @classmethod
    def non_empty_strings(cls, value: list[str]) -> list[str]:
        _require_text_items(value)
        return value

    @field_validator("aspect_ratios")
    @classmethod
    def aspect_ratio_items(cls, value: list[str]) -> list[str]:
        _require_text_items(value)
        for item in value:
            if re.fullmatch(ASPECT_RATIO_PATTERN, item) is None:
                raise ValueError("aspect ratio must look like 16:9")
        return value

    @field_validator("languages")
    @classmethod
    def language_items(cls, value: list[str]) -> list[str]:
        _require_text_items(value)
        for item in value:
            if re.fullmatch(LANGUAGE_PATTERN, item) is None:
                raise ValueError("language must be a short BCP 47 tag")
        return value

    @field_validator("open_questions")
    @classmethod
    def at_most_two_questions(cls, value: list[ClarifyingQuestion]) -> list[ClarifyingQuestion]:
        if len(value) > 2:
            raise ValueError("at most 2 open questions")
        return value


def _require_text_items(value: list[str]) -> None:
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("items must be non-empty strings")
