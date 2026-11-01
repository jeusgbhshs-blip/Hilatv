"""Packaging styles under templates/packaging. Limits from SPEC stay in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fractions import Fraction
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
    ratio = _aspect(aspect) if aspect is not None else None
    if width is not None or height is not None:
        if width is None or height is None:
            raise ValueError("render width and height must be supplied together")
        return _checked_size(width, height, ratio)
    env_w = os.getenv("HILATV_RENDER_WIDTH", "").strip()
    env_h = os.getenv("HILATV_RENDER_HEIGHT", "").strip()
    if env_w and env_h:
        configured = _checked_size(int(env_w), int(env_h), None)
        # Old global landscape test settings must not turn an explicit portrait
        # project into a landscape movie. Only matching, smaller sizes apply.
        if ratio is None:
            return configured
        default = aspect_size(aspect)
        if (
            configured[0] * ratio.denominator == configured[1] * ratio.numerator
            and configured[0] <= default[0]
            and configured[1] <= default[1]
        ):
            return configured
    return aspect_size(aspect or "16:9")


def aspect_size(aspect: str, long_edge: int | None = None) -> tuple[int, int]:
    """An exact, even-pixel aspect, bounded by the requested long edge."""

    ratio = _aspect(aspect)
    edge = (720 if ratio == 1 else 1280) if long_edge is None else int(long_edge)
    unit = max(ratio.numerator, ratio.denominator)
    multiplier = edge // (2 * unit) * 2
    if multiplier < 2 or min(ratio.numerator, ratio.denominator) * multiplier < 16:
        raise ValueError("render dimensions are too small for the requested aspect ratio")
    return ratio.numerator * multiplier, ratio.denominator * multiplier


def _aspect(aspect: str) -> Fraction:
    try:
        left, right = aspect.split(":")
        if not left.isdigit() or not right.isdigit() or int(left) <= 0 or int(right) <= 0:
            raise ValueError
        return Fraction(int(left), int(right))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("aspect ratio must contain two positive integers") from exc


def _checked_size(width: int, height: int, ratio: Fraction | None) -> tuple[int, int]:
    if width < 16 or height < 16 or width % 2 or height % 2:
        raise ValueError("render dimensions must be even integers of at least 16 pixels")
    if ratio is not None and width * ratio.denominator != height * ratio.numerator:
        raise ValueError("render dimensions do not match the requested aspect ratio")
    return width, height


def quantize_s(seconds: float, fps: int = FPS) -> float:
    frames = max(1, int(round(float(seconds) * fps)))
    return frames / fps
