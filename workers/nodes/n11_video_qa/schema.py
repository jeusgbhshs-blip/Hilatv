"""N11 envelopes. Video candidates are chapter 5 models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from workers.schemas.asset import Candidate


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


class N11Input(BaseModel):
    candidates: list[Candidate] = Field(min_length=1)
    anchors: dict[str, str] = Field(default_factory=dict)
    expected_faces: dict[str, int] = Field(default_factory=dict)
