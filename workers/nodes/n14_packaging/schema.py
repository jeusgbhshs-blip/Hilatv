"""N14 envelopes. Brand fields and on-screen cards are chapter 5 models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.script import Script

LogoStatus = Literal["ready", "mock", "missing", "unknown"]


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


class N14Input(BaseModel):
    script: Script
    brand_kit: BrandKit | None = None
    enterprise_id: str | None = None
    brief: Brief | None = None
    intro: str | None = None
    corner_logo: bool | None = None
    # False drops intro, corner, and ending logo cards. None keeps today's overlays.
    brand_logo: bool | None = None
    width: int | None = Field(default=None, ge=16)
    height: int | None = Field(default=None, ge=16)
    work_dir: str | None = None


class PackageElement(BaseModel):
    """One render-layer overlay. ``spec`` is enough to redraw the PNG."""

    element_id: str
    kind: str
    template: str = ""
    text: str = ""
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    x_ratio: float = 0
    y_ratio: float = 0
    anchor: str = "topleft"
    png_path: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)
    logo_status: LogoStatus = "unknown"
