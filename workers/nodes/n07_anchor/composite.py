"""Paste a real cutout into a placeholder scene without resampling it.

The contact quad is recorded for the camera. The bitmap is copied. Resampling
would change logo and packaging pixels, which SPEC §1.4 requires to stay
identical to the original. Opaque pixels are checked against the original.
Shape deformation is not measured: a cosine against a recomposite of the same
cutout would only repeat this paste.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.qa.rules import inspect_image

_TEXT = frozenset({"garbled_text", "extra_text"})
# Not a score. The paste is not a perspective resample, so deformation is unmeasured.
DEFORMATION_UNMEASURED = "未测形变"


@dataclass(frozen=True)
class CompositeAudit:
    pixel_matches: int
    deformation: str
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
    if count < 1:
        raise ValueError("product region has no opaque pixels to compare")
    del scene
    return CompositeAudit(
        pixel_matches=count,
        deformation=DEFORMATION_UNMEASURED,
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
