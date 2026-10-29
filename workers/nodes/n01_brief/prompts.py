"""Jinja prompt rendering for N1. User text is inserted as data, not as a template."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from workers.schemas.brand import BrandKit

PROMPTS = Path(__file__).resolve().parent / "prompts"
NO_DRAWN_TEXT = "Do not render any on-screen text, logos, prices, or phone numbers."

_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def system_prompt() -> str:
    return _ENV.get_template("system.j2").render().strip()


def render_extract(
    *,
    raw_input: str,
    attachment_summary: str,
    brand_summary: str,
    feedback: str = "",
) -> str:
    return (
        _ENV.get_template("extract_brief.j2")
        .render(
            raw_input=raw_input,
            attachment_summary=attachment_summary,
            brand_summary=brand_summary,
            feedback=feedback,
        )
        .strip()
    )


def render_classify(*, filename: str, alt: str, source: str) -> str:
    return (
        _ENV.get_template("classify_image.j2")
        .render(
            filename=filename,
            alt=alt,
            source=source,
        )
        .strip()
    )


def summarize_brand(brand: BrandKit | None) -> str:
    if brand is None:
        return "无"
    products = "；".join(
        f"{item.name}（卖点：{'、'.join(item.selling_points) or '无'}）" for item in brand.products
    )
    return (
        f"企业：{brand.company_name}；行业：{brand.industry.value}；"
        f"调性：{brand.tone}；产品：{products or '无'}。"
        "Logo 与电话只供后期叠加，不要画进画面。"
    )
