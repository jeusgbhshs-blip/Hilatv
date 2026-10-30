"""N7 envelopes. Anchor rows point at chapter 5 assets; shots use Candidate."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from workers.schemas.brief import Brief
from workers.schemas.script import Script


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


class ProductImage(BaseModel):
    """Bytes or a brand/http URI. Filesystem paths are not accepted from callers."""

    model_config = ConfigDict(extra="ignore")

    product_id: str | None = None
    name: str | None = None
    image_b64: str | None = None
    uri: str | None = None


class N7Input(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enterprise_id: str | None = None
    brand_id: str | None = None
    brand_kit: dict[str, Any] | None = None
    brief: Brief | None = None
    script: Script | None = None
    concept: dict[str, Any] | None = None
    products: list[ProductImage] = Field(default_factory=list)
