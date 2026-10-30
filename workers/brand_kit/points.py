"""Selling points from source text, plus the preference write-back."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from workers.schemas.brand import BrandKit, Product, find_banned_words

_SPLIT = re.compile(r"[。！？\n；;]+")
_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


class PointDraft(BaseModel):
    """Loose LLM extraction. Empty defaults keep an unkeyed mock from inventing points."""

    model_config = ConfigDict(extra="ignore")

    points: list[str] = Field(default_factory=list)


class Replacement(BaseModel):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1)


class PreferenceEdit(BaseModel):
    """A user change that should stick for the next film."""

    product_name: str | None = None
    replacements: list[Replacement] = Field(default_factory=list)
    drop_lines: list[str] = Field(default_factory=list)


class PreferenceError(ValueError):
    retryable = False


def extract_selling_points(
    *,
    manual: list[str],
    source_text: str,
    banned: list[str],
    gateway: Any | None = None,
    project_id: str = "",
    attempt: int = 1,
) -> list[str]:
    """Manual lines win. Model lines are kept only when they already appear in the source."""

    kept = _clean(manual, banned)
    drafted: list[str] = []
    if gateway is not None and source_text.strip():
        prompt = _ENV.get_template("points.j2").render(
            banned="、".join(banned),
            manual="、".join(kept) or "无",
            source=source_text[:4000],
            feedback="",
        )
        try:
            raw = gateway.generate_text(
                prompt,
                schema=PointDraft,
                seed=0,
                project_id=project_id,
                node="n02_brand_kit",
                shot_id=None,
                attempt=attempt,
            )
            draft = PointDraft.model_validate(raw)
        except Exception:
            draft = PointDraft()
        source = source_text
        for point in draft.points:
            text = point.strip()
            if text and text in source and not find_banned_words(text, banned):
                drafted.append(text)
    for point in _from_text(source_text, banned):
        drafted.append(point)
    merged: list[str] = []
    for point in [*kept, *drafted]:
        if point not in merged:
            merged.append(point)
    return merged[:6]


def apply_preference(kit: BrandKit, edit: PreferenceEdit) -> tuple[BrandKit, dict[str, Any]]:
    """Write a selling-point change back onto the kit and remember the dropped line."""

    banned = list(kit.banned_words)
    for line in edit.drop_lines:
        if line and line not in banned:
            banned.append(line)
    products: list[Product] = []
    for product in kit.products:
        points = list(product.selling_points)
        if edit.product_name in (None, product.name):
            for change in edit.replacements:
                if find_banned_words(change.new, kit.banned_words):
                    raise PreferenceError(f"卖点含有禁用词：{change.new}")
                points = [change.new if point == change.old else point for point in points]
            points = [point for point in points if point not in edit.drop_lines]
        products.append(product.model_copy(update={"selling_points": points}))
    updated = kit.model_copy(update={"products": products, "banned_words": banned})
    record = {
        "product_name": edit.product_name,
        "replacements": [item.model_dump() for item in edit.replacements],
        "dropped_lines": [line for line in edit.drop_lines if line],
    }
    return updated, record


def _clean(points: list[str], banned: list[str]) -> list[str]:
    cleaned: list[str] = []
    for point in points:
        text = point.strip()
        if text and not find_banned_words(text, banned) and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _from_text(source: str, banned: list[str]) -> list[str]:
    found: list[str] = []
    for part in _SPLIT.split(source):
        text = part.strip(" ，,、")
        if 2 <= len(text) <= 40 and not find_banned_words(text, banned):
            found.append(text)
    return found
