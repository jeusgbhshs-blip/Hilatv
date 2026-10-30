"""User-facing progress lines. Kept out of the workflow sandbox."""

from __future__ import annotations


def shot_message(order: int, action: str) -> str:
    """SPEC §10.1, for example 「第 3 镜：正在生成画面」."""

    return f"第 {int(order)} 镜：{action}"
