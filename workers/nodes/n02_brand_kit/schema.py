"""N2 envelopes. The stored document is the chapter 5 BrandKit."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from workers.brand_kit.points import PreferenceEdit


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


class ProductIntake(BaseModel):
    name: str = Field(min_length=1)
    photo_b64: str = Field(min_length=1)
    selling_points: list[str] = Field(default_factory=list)
    source_text: str = ""
    forbidden_changes: list[str] = Field(default_factory=list)


class PersonIntake(BaseModel):
    role: str = Field(min_length=1)
    consent: bool
    voice_id: str | None = None


class N2Input(BaseModel):
    mode: Literal["resolve", "build", "preference"] = "resolve"
    enterprise_id: str | None = None
    brand_id: str | None = None
    inline: dict[str, Any] | None = None
    company_name: str | None = None
    industry: str | None = None
    logo_b64: str | None = None
    products: list[ProductIntake] = Field(default_factory=list)
    people: list[PersonIntake] = Field(default_factory=list)
    tone: str = "专业、可靠、不夸张"
    phone: str = ""
    website: str = ""
    wechat_qr: str = ""
    title_font: str = "NotoSansSC-Bold"
    body_font: str = "NotoSansSC-Regular"
    extra_banned_words: list[str] = Field(default_factory=list)
    preference: PreferenceEdit | None = None
