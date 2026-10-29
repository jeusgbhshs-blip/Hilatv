"""Custom pronunciation dictionary for polyphonic characters and product terms."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Lexeme:
    text: str
    pinyin: str


def lexicon_path() -> Path:
    override = os.getenv("HILATV_N6_LEXICON", "").strip()
    if override:
        return Path(override)
    return Path(__file__).with_name("lexicon.yaml")


def load_lexicon(path: Path | None = None) -> tuple[Lexeme, ...]:
    target = path or lexicon_path()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"lexicon must be a mapping: {target}")
    entries: list[Lexeme] = []
    for item in raw.get("entries") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        pinyin = str(item.get("pinyin") or "").strip()
        if text and pinyin:
            entries.append(Lexeme(text, pinyin))
    entries.sort(key=lambda item: len(item.text), reverse=True)
    return tuple(entries)


def matching_terms(text: str, lexicon: tuple[Lexeme, ...]) -> list[dict[str, str]]:
    """Non-overlapping hits, longer phrases first. The gateway receives only these."""

    occupied = [False] * len(text)
    found: list[dict[str, str]] = []
    for entry in lexicon:
        start = 0
        while True:
            index = text.find(entry.text, start)
            if index < 0:
                break
            end = index + len(entry.text)
            if not any(occupied[index:end]):
                for cursor in range(index, end):
                    occupied[cursor] = True
                found.append({"text": entry.text, "pinyin": entry.pinyin})
            start = index + 1
    return found
