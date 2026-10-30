"""Music prompt. The model is asked for an instrumental bed, never on-screen text."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

PROMPTS = Path(__file__).resolve().parent / "prompts"

_ENV = Environment(
    loader=FileSystemLoader(PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_music_prompt(*, mood: str, duration_s: float, bpm: float) -> str:
    return (
        _ENV.get_template("music.j2")
        .render(mood=mood, duration_s=round(duration_s, 3), bpm=round(bpm, 2))
        .strip()
    )
