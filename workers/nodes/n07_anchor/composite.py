"""Paste a real cutout into a placeholder scene without resampling it.

The contact quad is recorded for the camera. The bitmap is copied. Resampling
would change logo and packaging pixels, which SPEC §1.4 requires to stay
identical to the original. The similarity number is N11's deform threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.qa.pixels import shape_similarity
from workers.qa.rules import inspect_image
from workers.qa.settings import deform_min_similarity

_TEXT = frozenset({"garbled_text", "extra_text"})


@dataclass(frozen=True)
class CompositeAudit:
    pixel_matches: int
    similarity: float
    threshold: float
    origin: tuple[int, int]
    quad: list[list[int]]


def painted_text(image: Image.Image) -> str | None:
    findings = inspect_image(image, min_edge=1, check_composition=False, expected_faces=0)
    for item in findings:
        if item.code in _TEXT:
            return item.detail
    return None


def placement(scene: tuple[int, int], cutout: tuple[int, int]) -> tuple[int, int, list[list[int]]]:
    scene_w, scene_h = scene
    cut_w, cut_h = cutout
    if cut_w > scene_w or cut_h > scene_h or cut_w < 1 or cut_h < 1:
        raise ValueError("cutout does not fit the scene")
    x = (scene_w - cut_w) // 2
    y = max(0, scene_h - cut_h - 12)
    inset = min(4, cut_w // 8)
    quad = [
        [x + inset, y],
        [x + cut_w - inset, y],
        [x + cut_w, y + cut_h],
        [x, y + cut_h],
    ]
    return x, y, quad


def audit(
    composite: Image.Image,
    scene: Image.Image,
    cutout: Image.Image,
    original: Image.Image,
    origin: tuple[int, int],
    quad: list[list[int]],
) -> CompositeAudit:
    """Compare the pasted region with the original photo, not with itself."""

    if composite.size == cutout.size or composite.size == original.size:
        raise ValueError("composite must be the scene, not the cutout file")
    count = _opaque_matches(composite, cutout, original, origin)
    score = _similarity(composite, scene, cutout, origin)
    threshold = deform_min_similarity()
    if count < 1:
        raise ValueError("product region has no opaque pixels to compare")
    if score < threshold:
        raise ValueError(f"product similarity {score:.3f} is below {threshold:.3f}")
    return CompositeAudit(
        pixel_matches=count,
        similarity=score,
        threshold=threshold,
        origin=origin,
        quad=quad,
    )


def _opaque_matches(
    composite: Image.Image,
    cutout: Image.Image,
    original: Image.Image,
    origin: tuple[int, int],
) -> int:
    if cutout.size != original.size:
        raise ValueError("cutout size does not match the original photo")
    x0, y0 = origin
    src = original.convert("RGB").load()
    alpha = cutout.convert("RGBA").load()
    dst = composite.convert("RGB").load()
    count = 0
    for y in range(cutout.height):
        for x in range(cutout.width):
            if alpha[x, y][3] != 255:
                continue
            original_rgb = src[x, y]
            cutout_rgb = alpha[x, y][:3]
            if cutout_rgb != original_rgb:
                raise ValueError("matte changed an opaque product pixel")
            if dst[x0 + x, y0 + y] != original_rgb:
                raise ValueError("composited product pixel does not match the original")
            count += 1
    return count


def _similarity(
    composite: Image.Image,
    scene: Image.Image,
    cutout: Image.Image,
    origin: tuple[int, int],
) -> float:
    """Rebuild the product region from the scene file and the cutout file."""

    x0, y0 = origin
    box = (x0, y0, x0 + cutout.width, y0 + cutout.height)
    crop = composite.crop(box).convert("RGB")
    reference = scene.crop(box).convert("RGBA")
    reference.paste(cutout.convert("RGBA"), (0, 0), cutout.convert("RGBA"))
    _restore_opaque(reference, cutout)
    return shape_similarity(crop, reference.convert("RGB"))


def _restore_opaque(plate: Image.Image, cutout: Image.Image) -> None:
    dst = plate.load()
    src = cutout.convert("RGBA").load()
    for y in range(cutout.height):
        for x in range(cutout.width):
            red, green, blue, alpha = src[x, y]
            if alpha == 255:
                dst[x, y] = (red, green, blue, 255)
