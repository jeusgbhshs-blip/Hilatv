"""Shot-language presets. Each file is an original prompt fragment, not a copied library."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ShotPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    shot_sizes: list[str] = Field(min_length=1)
    purposes: list[str] = Field(min_length=1)
    prompt_fragment: str = Field(min_length=1)
    negative_fragment: str = Field(min_length=1)
    recommended_model: str = Field(min_length=1)
    motion_strength: str = Field(min_length=1)


def presets_dir() -> Path:
    override = os.getenv("HILATV_SHOT_TEMPLATES", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "templates" / "shots"


@lru_cache(maxsize=1)
def load_presets() -> tuple[ShotPreset, ...]:
    root = presets_dir()
    found: list[ShotPreset] = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        preset = ShotPreset.model_validate(data)
        if preset.id != path.stem:
            raise ValueError(f"{path.name} declares {preset.id}")
        negative = preset.negative_fragment
        if "text" not in negative.lower() and "文字" not in negative:
            raise ValueError(f"{preset.id} is missing a no-text constraint")
        found.append(preset)
    if not found:
        raise ValueError(f"no shot presets in {root}")
    ids = [item.id for item in found]
    if len(ids) != len(set(ids)):
        raise ValueError("shot preset ids must be unique")
    return tuple(found)


def reset_presets() -> None:
    load_presets.cache_clear()


def match_preset(presets: tuple[ShotPreset, ...], shot_size: str, role: str) -> ShotPreset:
    ranked: list[tuple[int, str, ShotPreset]] = []
    for preset in presets:
        size_ok = shot_size in preset.shot_sizes
        role_ok = role in preset.purposes
        if size_ok and role_ok:
            rank = 0
        elif size_ok:
            rank = 1
        elif role_ok:
            rank = 2
        else:
            rank = 3
        ranked.append((rank, preset.id, preset))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]
