"""Generation mode follows the N5 bullets, with the documented priority."""

from __future__ import annotations

import json
from pathlib import Path

from workers.nodes.n05_storyboard.modes import select_generation_mode
from workers.schemas.brand import BrandKit
from workers.schemas.script import GenerationMode

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


def _brand() -> BrandKit:
    raw = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))
    return BrandKit.model_validate(raw)


def test_mode_table() -> None:
    brand = _brand()
    photos_only = brand.model_copy(deep=True)
    photos_only.products[0].cutouts = []
    no_image = brand.model_copy(deep=True)
    no_image.products[0].photos = []
    no_image.products[0].cutouts = []

    assert select_generation_mode("参数", brand) is GenerationMode.motion_graphics
    assert select_generation_mode("流程", brand) is GenerationMode.motion_graphics
    assert select_generation_mode("行动号召", brand) is GenerationMode.motion_graphics
    assert select_generation_mode("人物出镜", brand) is GenerationMode.reference_to_video
    assert select_generation_mode("卖点", brand) is GenerationMode.product_composite
    assert select_generation_mode("卖点", photos_only) is GenerationMode.reference_to_video
    assert select_generation_mode("卖点", no_image) is GenerationMode.image_to_video
    assert select_generation_mode("卖点", None) is GenerationMode.image_to_video
    assert select_generation_mode("钩子", brand) is GenerationMode.text_to_video
    assert select_generation_mode("信任证明", brand) is GenerationMode.text_to_video
    assert select_generation_mode("钩子", brand, scene_still=True) is GenerationMode.image_to_video
    assert select_generation_mode("卖点", brand) is not GenerationMode.first_last_frame
