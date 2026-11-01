"""Explicit user generation choices; null keeps the existing inference path."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from workers.schemas.base import JsonInt, SchemaModel

AspectRatio = Literal["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9"]


class GenerationSettings(SchemaModel):
    """Duration is the whole film, including any intro and outro packaging."""

    aspect_ratio: AspectRatio | None = None
    duration_s: JsonInt | None = Field(default=None, ge=5, le=180)


def generation_settings(value: object = None) -> GenerationSettings:
    """Normalize missing legacy values without accepting malformed user fields."""

    if value is None:
        return GenerationSettings()
    return GenerationSettings.model_validate(value)
