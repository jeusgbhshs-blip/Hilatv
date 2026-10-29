"""Load the six chapter 7 industry templates."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from workers.nodes.n01_brief.platforms import aspects_match

INDUSTRY_ORDER: tuple[str, ...] = (
    "manufacturing",
    "foreign_trade",
    "ecommerce",
    "local_life",
    "education",
    "public_sector",
)


class Keyword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    weight: int = Field(ge=1)


class VideoTypeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class IndustryTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industry: str = Field(min_length=1)
    label: str = Field(min_length=1)
    narrative: list[str] = Field(min_length=1)
    shot_sequence: list[str] = Field(min_length=1)
    duration_s: int = Field(ge=5, le=180)
    aspect_ratios: list[str] = Field(min_length=1)
    platforms: list[str] = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    style_keywords: list[str] = Field(min_length=1)
    music_mood: str = Field(min_length=1)
    must_include: list[str] = Field(min_length=1)
    forbidden: list[str] = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    video_types: list[VideoTypeSpec] = Field(min_length=1)
    default_video_type: str = Field(min_length=1)
    keywords: list[Keyword] = Field(min_length=1)
    clarify_question: str = ""

    @property
    def style_default(self) -> str:
        return "、".join(self.style_keywords)

    def video(self, type_id: str) -> VideoTypeSpec:
        for item in self.video_types:
            if item.id == type_id:
                return item
        raise KeyError(type_id)

    @property
    def default_video(self) -> VideoTypeSpec:
        return self.video(self.default_video_type)


def templates_dir() -> Path:
    override = os.getenv("HILATV_INDUSTRY_TEMPLATES", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "templates" / "industries"


@lru_cache(maxsize=1)
def load_industries() -> dict[str, IndustryTemplate]:
    root = templates_dir()
    found: dict[str, IndustryTemplate] = {}
    for industry in INDUSTRY_ORDER:
        path = root / f"{industry}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        template = IndustryTemplate.model_validate(data)
        if template.industry != industry:
            raise ValueError(f"{path.name} declares {template.industry}")
        template.video(template.default_video_type)
        if len(template.video_types) > 1 and not template.clarify_question.strip():
            raise ValueError(f"{industry} needs a clarify question")
        if not aspects_match(template.platforms, template.aspect_ratios):
            raise ValueError(f"{industry} default platforms and aspects do not match")
        found[industry] = template
    return found


def reset_industries() -> None:
    load_industries.cache_clear()


def detect_industry(text: str) -> str | None:
    """Highest keyword weight wins. Ties break toward the chapter 7 table order."""

    lowered = text.lower()
    scored: list[tuple[int, int, int, str]] = []
    templates = load_industries()
    for index, industry in enumerate(INDUSTRY_ORDER):
        template = templates[industry]
        total = 0
        best = 0
        for keyword in template.keywords:
            if keyword.text.lower() in lowered:
                total += keyword.weight
                best = max(best, keyword.weight)
        if total:
            scored.append((total, best, -index, industry))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][3]


def match_video_type(template: IndustryTemplate, text: str) -> str | None:
    lowered = text.lower()
    hits: list[tuple[int, int, str]] = []
    for index, spec in enumerate(template.video_types):
        best_len = 0
        for keyword in spec.keywords:
            if keyword.lower() in lowered:
                best_len = max(best_len, len(keyword))
        if best_len:
            hits.append((best_len, -index, spec.id))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][2]


def industry_from_name(value: str) -> str | None:
    text = value.strip()
    if not text or text.lower() in {"mock", "string", "none", "null"}:
        return None
    templates = load_industries()
    if text in templates:
        return text
    for industry, template in templates.items():
        if text == template.label:
            return industry
    return None


def video_from_name(template: IndustryTemplate, value: str) -> str | None:
    text = value.strip()
    if not text or text.lower() in {"mock", "string", "none", "null"}:
        return None
    for spec in template.video_types:
        if text in {spec.id, spec.label}:
            return spec.id
    return None
