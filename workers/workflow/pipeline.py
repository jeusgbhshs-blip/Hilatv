"""Planned node order. The running T10 line is ``workers.workflow.film``."""

from __future__ import annotations

PLANNED_NODES: tuple[str, ...] = (
    "n01_brief",
    "n02_brand_kit",
    "n03_concept",
    "n04_script",
    "n05_storyboard",
    "n06_voice",
    "n07_anchor",
    "n08_keyframe",
    "n09_keyframe_qa",
    "n10_image_to_video",
    "n11_video_qa",
    "n12_music",
    "n13_subtitle",
    "n14_packaging",
    "n15_edit",
    "n16_final_qa",
    "n17_delivery",
    "n18_revision",
)


def planned_nodes() -> list[str]:
    return list(PLANNED_NODES)
