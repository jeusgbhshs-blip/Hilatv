"""Shared gateway request and response models."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    task: Literal["llm", "image", "video", "tts", "asr", "music", "review"]
    prompt: str = ""
    payload: dict[str, object] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    output: dict[str, object]
    cost_cny: float


class Adapter(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse: ...
