"""Deterministic mock documents satisfy nested Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from gateway.schema_util import fill_json_schema


class ShotRef(BaseModel):
    shot_id: str
    order: int = Field(ge=1)


class Wrap(BaseModel):
    shot: ShotRef
    tags: list[str] = Field(min_length=1)
    note: str | None = None


def test_nested_ref_and_min_items_validate() -> None:
    raw = fill_json_schema(Wrap.model_json_schema())
    parsed = Wrap.model_validate(raw)
    assert parsed.shot.order >= 1
    assert parsed.tags
    assert parsed.note is None
    assert fill_json_schema(Wrap.model_json_schema()) == raw
