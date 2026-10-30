"""Shared Brand Kit and product matting.

T13 should import this package for cutouts, colors, consent, and anchor
angles. Nodes call it; they do not keep a second copy of the algorithm.
"""

from workers.brand_kit.angles import AnchorRef, complete_angles
from workers.brand_kit.assemble import BuildInput, BuildOutput, build_brand_kit
from workers.brand_kit.colors import extract_colors
from workers.brand_kit.matting import Cutout, EdgeReport, ReplaceImageError, matte, mono_plate
from workers.brand_kit.people import (
    ConsentError,
    people_for_use,
    release_kit,
    require_consent,
    usable_people,
)
from workers.brand_kit.points import PreferenceEdit, apply_preference, extract_selling_points
from workers.brand_kit.store import BrandReadError, open_brand_root, resolve_kit

__all__ = [
    "AnchorRef",
    "BrandReadError",
    "BuildInput",
    "BuildOutput",
    "ConsentError",
    "Cutout",
    "EdgeReport",
    "PreferenceEdit",
    "ReplaceImageError",
    "apply_preference",
    "build_brand_kit",
    "complete_angles",
    "extract_colors",
    "extract_selling_points",
    "matte",
    "mono_plate",
    "open_brand_root",
    "people_for_use",
    "release_kit",
    "require_consent",
    "resolve_kit",
    "usable_people",
]
