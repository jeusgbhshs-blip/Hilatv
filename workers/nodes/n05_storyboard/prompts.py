"""Jinja prompts for N5."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from workers.nodes.n05_storyboard.presets import ShotPreset
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


def render_storyboard(
    *,
    script: Script,
    presets: tuple[ShotPreset, ...],
    duration_s: int,
    min_s: float,
    max_s: float,
    feedback: str = "",
) -> str:
    lines = [
        (
            f"{item.id}（{item.label}，景别 {'/'.join(item.shot_sizes)}，"
            f"推荐模型 {item.recommended_model}）"
        )
        for item in presets
    ]
    voiceover = "\n".join(f"{section.kind.value}: {section.text}" for section in script.sections)
    return (
        _ENV.get_template("storyboard.j2")
        .render(
            presets="\n".join(lines),
            voiceover=voiceover,
            duration_s=duration_s,
            min_s=min_s,
            max_s=max_s,
            feedback=feedback,
        )
        .strip()
    )
