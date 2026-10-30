"""Director decisions (SPEC chapter 4) and the N18 revision directive."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from workers.schemas.base import NODE_ID_PATTERN, JsonInt, SchemaModel


class DecisionAction(StrEnum):
    """Chapter 4 outcomes: 通过 / 重生 / 换模型 / 降级方案 / 求助用户.

    The sample decision uses ``regenerate``.
    """

    pass_ = "pass"
    regenerate = "regenerate"
    switch_model = "switch_model"
    fallback = "fallback"
    ask_user = "ask_user"


class DecisionTarget(SchemaModel):
    node: str = Field(pattern=NODE_ID_PATTERN)
    shot_id: str | None = None


class DirectorDecision(SchemaModel):
    action: DecisionAction
    target: DecisionTarget
    reason: str = Field(min_length=1)
    changes: dict[str, Any]
    max_attempts_left: JsonInt = Field(ge=0, le=3)


class RevisionDirective(SchemaModel):
    """N18 change set: ``{targets, change, keep}``."""

    targets: list[str] = Field(min_length=1)
    change: dict[str, Any]
    keep: list[str] = Field(default_factory=list)

    @field_validator("targets", "keep")
    @classmethod
    def non_empty_items(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or not item:
                raise ValueError("items must be non-empty strings")
        return value

    @model_validator(mode="after")
    def visible_ai_label_cannot_be_removed(self) -> RevisionDirective:
        from workers.schemas.label_lock import LabelLocked, walk_label_edits

        try:
            walk_label_edits(self.change)
            walk_label_edits(self.keep)
        except LabelLocked as exc:
            raise ValueError(str(exc)) from exc
        return self
