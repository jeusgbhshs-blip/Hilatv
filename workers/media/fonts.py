"""Noto Sans SC (Source Han Sans) files shipped under templates/packaging/fonts."""

from __future__ import annotations

import os
from pathlib import Path

from workers.media.packaging import packaging_dir

_FILES = {
    "regular": "NotoSansSC-Regular.otf",
    "bold": "NotoSansSC-Bold.otf",
}

_ALIASES = {
    "notosanssc-regular": "regular",
    "notosanssc-bold": "bold",
    "noto sans cjk sc": "regular",
    "source han sans sc": "regular",
    "body": "regular",
    "title": "bold",
}


def font_dir() -> Path:
    override = os.getenv("HILATV_FONT_DIR", "").strip()
    if override:
        return Path(override)
    return packaging_dir() / "fonts"


def resolve_font(weight: str) -> Path:
    key = _ALIASES.get(weight.strip().lower(), weight.strip().lower())
    if key not in _FILES:
        key = "bold" if "bold" in key else "regular"
    path = font_dir() / _FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"missing Noto Sans SC font: {path}")
    return path
