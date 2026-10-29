"""N5 generation-mode rules from SPEC chapter 6.

Priority when a shot could match more than one bullet:
data / process / call-to-action, then a person who is on screen continuously,
then a real product image, then an empty atmosphere shot.
``first_last_frame`` is not chosen here; N5's four bullets do not name it.
"""

from __future__ import annotations

from workers.schemas.brand import BrandKit
from workers.schemas.script import GenerationMode

_DATA = ("参数", "流程", "行动号召")
_ATMOS = ("钩子", "信任", "氛围")


def select_generation_mode(
    purpose: str,
    brand: BrandKit | None,
    *,
    scene_still: bool = False,
) -> GenerationMode:
    if "人物" in purpose:
        return GenerationMode.reference_to_video
    if any(token in purpose for token in _DATA):
        return GenerationMode.motion_graphics
    if "卖点" in purpose:
        product = brand.products[0] if brand and brand.products else None
        if product and product.cutouts:
            return GenerationMode.product_composite
        if product and product.photos:
            return GenerationMode.reference_to_video
        return GenerationMode.image_to_video
    if scene_still and any(token in purpose for token in _ATMOS):
        return GenerationMode.image_to_video
    return GenerationMode.text_to_video
