"""Node run envelope (project, payload, attempt).

Chapter 5 documents live in ``workers.schemas``. T05 will put a Brief in ``payload``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
