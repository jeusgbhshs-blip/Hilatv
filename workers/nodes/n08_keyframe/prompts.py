"""Per-model keyframe prompts. On-screen copy is never part of the prompt."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from gateway.constants import NO_RENDERED_TEXT

PROMPTS = Path(__file__).resolve().parent / "prompts"

_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def template_for(model: str) -> str:
    name = model.lower()
    if "kling" in name:
        return "kling_image.j2"
    if "seedream" in name:
        return "seedream.j2"
    return "default.j2"


def render_keyframe(
    *,
    model: str,
    camera: str,
    subject: str,
    scene: str,
    style: str,
    negative: str,
) -> str:
    text = (
        _ENV.get_template(template_for(model))
        .render(
            camera=camera,
            subject=subject,
            scene=scene,
            style=style,
            negative=negative,
        )
        .strip()
    )
    if NO_RENDERED_TEXT not in text:
        text = f"{text}\n{NO_RENDERED_TEXT}"
    return text


def negative_text(preset_negative: str) -> str:
    extra = preset_negative.strip()
    if extra and NO_RENDERED_TEXT not in extra:
        return f"{extra} {NO_RENDERED_TEXT}"
    return extra or NO_RENDERED_TEXT
