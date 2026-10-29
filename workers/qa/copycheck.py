"""Shared copy rules for N4 and N5.

Digit tokens in the spoken script and in on-screen text must already appear in
the brief or the brand kit. Spelled-out numbers are not treated as digits.
"""

from __future__ import annotations

import math
import re

from workers.schemas.brand import BrandKit, default_banned_words, find_banned_words
from workers.schemas.brief import Brief

ZH_RATE = 4.0
EN_RATE = 2.5
BREATH = 0.85
HOOK_SECONDS = 3.0
TOLERANCE = 0.05

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_EN_WORD = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def language_family(language: str) -> str:
    """Chinese uses a character rate. Every other language uses a word rate."""

    primary = language.lower().split("-", 1)[0]
    if primary == "zh":
        return "zh"
    return "en"


def speech_rate(language: str) -> float:
    return ZH_RATE if language_family(language) == "zh" else EN_RATE


def target_units(duration_s: float, language: str) -> float:
    """SPEC N4: 总字数 = 时长 × 速率 × 0.85."""

    return duration_s * speech_rate(language) * BREATH


def hook_unit_limit(language: str) -> int:
    """The hook has to be speakable inside the first 3 seconds, before the 0.85 breath."""

    return int(math.floor(HOOK_SECONDS * speech_rate(language) + 1e-9))


def count_units(text: str, language: str) -> int:
    if language_family(language) == "zh":
        return _zh_units(text)
    return _en_units(text)


def spoken_seconds(text: str, language: str) -> float:
    rate = speech_rate(language)
    if rate <= 0:
        return 0.0
    return count_units(text, language) / rate


def within_target(actual: int, target: float) -> bool:
    if target <= 0:
        return actual == 0
    return abs(actual - target) / target <= TOLERANCE + 1e-12


def unit_window(target: float) -> tuple[int, int]:
    """Inclusive integer counts whose relative error is within 5%."""

    if target <= 0:
        return 0, 0
    center = int(round(target))
    span = max(8, int(math.ceil(target * 0.2)) + 2)
    good = [n for n in range(max(0, center - span), center + span + 1) if within_target(n, target)]
    if not good:
        raise ValueError(f"no integer unit count within 5% of {target}")
    return good[0], good[-1]


def number_tokens(text: str) -> list[str]:
    return _NUMBER.findall(text)


def banned_for(brand: BrandKit | None) -> list[str]:
    if brand is None:
        return default_banned_words()
    return [word for word in brand.banned_words if word]


def strip_banned(text: str, banned: list[str]) -> str:
    cleaned = text
    for word in sorted({item for item in banned if item}, key=len, reverse=True):
        cleaned = cleaned.replace(word, "")
    return re.sub(r"\s+", " ", cleaned).strip()


def source_corpus(brief: Brief, brand: BrandKit | None) -> str:
    """Facts a digit is allowed to come from. Colors, ids, and assumptions are out."""

    parts: list[str] = [
        brief.raw_input,
        brief.goal,
        brief.audience,
        brief.style,
        brief.video_type,
        str(brief.duration_s),
    ]
    parts.extend(brief.must_include)
    parts.extend(brief.platform)
    parts.extend(brief.languages)
    if brand is not None:
        parts.extend(
            [
                brand.company_name,
                brand.tone,
                brand.cta.phone,
                brand.cta.website,
            ]
        )
        for product in brand.products:
            parts.append(product.name)
            parts.extend(product.selling_points)
            parts.extend(product.forbidden_changes)
        for person in brand.people:
            if person.consent:
                parts.append(person.role)
    return "\n".join(part for part in parts if part)


def allowed_numbers(brief: Brief, brand: BrandKit | None) -> set[str]:
    return set(number_tokens(source_corpus(brief, brand)))


def invented_numbers(text: str, allowed: set[str]) -> list[str]:
    found: list[str] = []
    for token in number_tokens(text):
        if token not in allowed and token not in found:
            found.append(token)
    return found


def banned_hits(text: str, banned: list[str]) -> list[str]:
    return find_banned_words(text, banned)


def normalize_phrase(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace()).lower()


def phrase_is_sourced(text: str, sources: list[str]) -> bool:
    needle = normalize_phrase(text)
    if len(needle) < 2:
        return False
    for source in sources:
        hay = normalize_phrase(source)
        if len(hay) < 2:
            continue
        if needle == hay or hay in needle or needle in hay:
            return True
    return False


def _zh_units(text: str) -> int:
    count = 0
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            count += 1
        elif ch.isascii() and ch.isalnum():
            count += 1
    return count


def _en_units(text: str) -> int:
    cjk = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)
    return cjk + len(_EN_WORD.findall(text))
