"""Text the compliance review sends to content safety and the extreme-word list."""

from __future__ import annotations

from workers.schemas.brand import BrandKit, default_banned_words, find_banned_words
from workers.schemas.brief import Brief
from workers.schemas.script import Script


def bundle_text(
    brief: Brief | None,
    script: Script | None,
    extra: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if brief is not None:
        parts.extend(
            [
                brief.raw_input,
                brief.goal,
                brief.video_type,
                brief.audience,
                brief.style,
                *brief.must_include,
                *brief.platform,
            ]
        )
    if script is not None:
        for shot in script.shots:
            parts.extend([shot.purpose, shot.visual, shot.voiceover])
            parts.extend(card.text for card in shot.on_screen_text)
    parts.extend(extra or [])
    return "\n".join(part.strip() for part in parts if part and part.strip())


def extreme_hits(text: str, brand: BrandKit | None) -> list[str]:
    if brand is not None and brand.banned_words:
        banned = list(brand.banned_words)
    else:
        banned = default_banned_words()
    return find_banned_words(text, banned)
