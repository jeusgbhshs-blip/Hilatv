"""Packaging styles under templates/packaging. Limits from SPEC stay in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ZH_MAX_CHARS = 16
EN_MAX_CHARS = 42
ALIGNMENT_MS = 100
FPS = 30
SUBTITLE_FONT_RATIO = 0.062
SUBTITLE_LINE_RATIO = 0.09
BADGE_FONT_RATIO = 0.078

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _ROOT / "templates" / "packaging"


def packaging_dir() -> Path:
    override = os.getenv("HILATV_PACKAGING_DIR", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_DIR


@dataclass(frozen=True)
class Insets:
    top: float
    bottom: float
    left: float
    right: float

    def merge_max(self, other: Insets) -> Insets:
        return Insets(
            top=max(self.top, other.top),
            bottom=max(self.bottom, other.bottom),
            left=max(self.left, other.left),
            right=max(self.right, other.right),
        )


def _load(name: str) -> dict:
    path = packaging_dir() / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


@lru_cache(maxsize=1)
def intro_spec() -> dict:
    return _load("intro.yaml")


@lru_cache(maxsize=1)
def outro_spec() -> dict:
    return _load("outro.yaml")


@lru_cache(maxsize=1)
def ai_label_text() -> str:
    text = str(_load("ai_label.yaml").get("text") or "").strip()
    if not text:
        raise ValueError("ai label text is empty")
    return text


@lru_cache(maxsize=1)
def lexicon_words() -> tuple[str, ...]:
    raw = _load("words.yaml").get("words") or []
    words = [str(item).strip() for item in raw if str(item).strip()]
    return tuple(sorted(set(words), key=len, reverse=True))


def safe_insets(platforms: list[str] | None) -> Insets:
    data = _load("safe_areas.yaml")
    default = data.get("default") or {}
    chosen = Insets(
        top=float(default.get("top", 0.08)),
        bottom=float(default.get("bottom", 0.12)),
        left=float(default.get("left", 0.06)),
        right=float(default.get("right", 0.06)),
    )
    names = [item.strip().lower() for item in (platforms or []) if item and item.strip()]
    if not names:
        return chosen
    matched = False
    for row in data.get("platforms") or []:
        aliases = [str(name).strip().lower() for name in row.get("names") or []]
        if not any(alias in names or alias in "".join(names) for alias in aliases):
            # Also match when the brief says "抖音" and the alias is "抖音".
            if not any(alias and alias in name for alias in aliases for name in names):
                continue
        matched = True
        inset = Insets(
            top=float(row.get("top", chosen.top)),
            bottom=float(row.get("bottom", chosen.bottom)),
            left=float(row.get("left", chosen.left)),
            right=float(row.get("right", chosen.right)),
        )
        chosen = chosen.merge_max(inset)
    if not matched:
        return Insets(
            top=float(default.get("top", 0.08)),
            bottom=float(default.get("bottom", 0.12)),
            left=float(default.get("left", 0.06)),
            right=float(default.get("right", 0.06)),
        )
    return chosen


def lut_path() -> Path:
    path = packaging_dir() / "lut" / "unified.cube"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def canvas_size(
    aspect: str | None,
    *,
    width: int | None = None,
    height: int | None = None,
) -> tuple[int, int]:
    if width and height:
        return int(width), int(height)
    env_w = os.getenv("HILATV_RENDER_WIDTH", "").strip()
    env_h = os.getenv("HILATV_RENDER_HEIGHT", "").strip()
    if env_w and env_h:
        return int(env_w), int(env_h)
    if aspect == "9:16":
        return 720, 1280
    if aspect == "1:1":
        return 720, 720
    return 1280, 720


def quantize_s(seconds: float, fps: int = FPS) -> float:
    frames = max(1, int(round(float(seconds) * fps)))
    return frames / fps
