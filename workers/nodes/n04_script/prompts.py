"""Jinja prompts for N4. User facts are inserted as data, not as a template."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from workers.nodes.n04_script.facts import SourceFacts
from workers.schemas.brief import Brief
from workers.schemas.script import Script

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


def render_draft(
    *,
    brief: Brief,
    facts: SourceFacts,
    hook_units: int,
    target: int,
    feedback: str = "",
    duration_s: float | None = None,
) -> str:
    return (
        _ENV.get_template("draft_script.j2")
        .render(
            hook_seconds=3,
            hook_units=hook_units,
            target_units=target,
            duration_s=brief.duration_s if duration_s is None else duration_s,
            company=facts.company or "无",
            product=facts.product_name or "无",
            points="\n".join(facts.points) or "无",
            proof=facts.proof,
            phone=facts.phone or "无",
            website=facts.website or "无",
            banned="、".join(facts.banned) or "无",
            raw_input=brief.raw_input,
            must_include="、".join(brief.must_include) or "无",
            feedback=feedback,
        )
        .strip()
    )


def render_localize(
    *,
    brief: Brief,
    facts: SourceFacts,
    language: str,
    master: Script,
    target: int,
    feedback: str = "",
    duration_s: float | None = None,
) -> str:
    master_text = "\n".join(section.text for section in master.sections)
    return (
        _ENV.get_template("localize.j2")
        .render(
            language=language,
            hook_seconds=3,
            target_units=target,
            duration_s=brief.duration_s if duration_s is None else duration_s,
            master_text=master_text,
            points="\n".join(facts.points) or "无",
            proof=facts.proof,
            phone=facts.phone or "无",
            website=facts.website or "无",
            banned="、".join(facts.banned) or "无",
            feedback=feedback,
        )
        .strip()
    )


def render_review(
    *,
    script: Script,
    facts: SourceFacts,
    feedback: str = "",
) -> str:
    return (
        _ENV.get_template("review.j2")
        .render(
            banned="、".join(facts.banned) or "无",
            corpus=facts.corpus,
            language=script.language,
            script_text="\n".join(section.text for section in script.sections),
            feedback=feedback,
        )
        .strip()
    )
