"""Per-model image-to-video prompts. On-screen copy stays out of the prompt."""

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
        return "kling_video.j2"
    if "wan" in name or "wanx" in name:
        return "wan.j2"
    if "seedance" in name:
        return "seedance.j2"
    return "default.j2"


def render_video(
    *,
    model: str,
    camera: str,
    subject: str,
    scene: str,
    style: str,
    motion: str,
    negative: str,
    closing: bool,
) -> str:
    text = (
        _ENV.get_template(template_for(model))
        .render(
            camera=camera,
            subject=subject,
            scene=scene,
            style=style,
            motion=motion,
            negative=negative,
            closing=closing,
        )
        .strip()
    )
    if NO_RENDERED_TEXT not in text:
        text = f"{text}\n{NO_RENDERED_TEXT}"
    return text
