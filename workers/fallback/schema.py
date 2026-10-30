"""Delivery notes for a downgraded shot.

A downgraded shot is never reported as a QA pass and never as reviewed.
``reviewed`` is true only for a shot that was not downgraded and whose
QAReport has ``visual_reviewed`` true. There is no reshoot marker.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ShotDelivery(BaseModel):
    shot_id: str
    fallback_level: int | None = None
    fallback_name: str = ""
    degraded: bool = False
    qa_passed: bool = False
    reviewed: bool = False
    # True when this clip was delivered without a vision review. Not a QA pass.
    needs_review: bool = False
    hard_fail: list[str] = Field(default_factory=list)
    note: str = ""
    media_path: str = ""
    camera: str = ""
    subject: str = ""


LEVELS: tuple[tuple[int, str, str], ...] = (
    (1, "regenerate", "换模型重生成"),
    (2, "image_to_video", "合格关键帧图生视频"),
    (3, "programmatic_camera", "关键帧程序化运镜"),
    (4, "motion_graphics", "动态图形"),
)


def level_title(level: int) -> tuple[str, str]:
    for number, name, title in LEVELS:
        if number == level:
            return name, title
    raise ValueError(f"unknown fallback level {level}")


def quality_note(level: int, detail: str) -> str:
    _name, title = level_title(level)
    text = f"内部质量记录：降级到第 {level} 级（{title}）。{detail}未计为质检通过，未计为已评审。"
    if "建议补拍" in text:
        raise ValueError("delivery note must not ask for a reshoot")
    return text
