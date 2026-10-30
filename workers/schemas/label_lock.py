"""The visible 「AI生成」 mark cannot be edited off.

The wording follows 《人工智能生成合成内容标识办法》(国信办通字〔2025〕2号,
published 2025-03-14, effective 2025-09-01), article 4: an export must keep a
label a viewer can see. Article 9 allows an unlabeled file only after a user
agreement and six months of logs. 推断: this product does not offer that path.
"""

from __future__ import annotations

import re
from typing import Any

LABEL_TEXT = "AI生成"

# Connectors stay short so 「不要出现 AI 标识」 (a content rule) is not a removal.
_REMOVAL = re.compile(
    r"(?:去掉|删除|移除|去除|拿掉|抹掉|隐藏|关闭|取消|不要|别留|别要|remove|hide|delete)"
    r"(?:\s|的|掉|了|这个|片中|成片|视频|画面)*"
    r"(?:AI\s*标识|AI标识|AI\s*生成|人工智能生成标识|人工智能标识|显式标识|"
    r"ai\s*label|ai\s*mark|ai\s*badge)",
    re.IGNORECASE,
)

_LOCKED_KEYS = frozenset(
    {
        "omit_ai_label",
        "hide_ai_label",
        "remove_ai_label",
        "show_ai_label",
        "ai_label",
        "drop_ai_label",
    }
)

_OFF = frozenset({False, None, 0, "0", "off", "false", "no", "remove", "hide", "omit"})

REFUSAL = (
    "显式标识「AI生成」是成片的固定层，不能去掉。"
    "《人工智能生成合成内容标识办法》第四条要求导出文件带有可被明显感知的标识"
    "（国信办通字〔2025〕2号，2025-03-14 公布，2025-09-01 施行，"
    "https://www.gov.cn/zhengce/zhengceku/202503/content_7014286.htm）。"
    "推断：本系统不提供该办法第九条的无标识导出。"
)


class LabelLocked(ValueError):
    """An edit asked to remove the visible AI label."""

    retryable = False


def removal_requested(text: str) -> bool:
    return bool(text and _REMOVAL.search(text))


def refuse_label_removal(text: str) -> None:
    """Reject one instruction. A hit never becomes a change set."""

    if removal_requested(text):
        raise LabelLocked(REFUSAL)


def _locked_key(key: str, value: Any) -> bool:
    if key not in _LOCKED_KEYS:
        return False
    if key in {"show_ai_label", "ai_label"}:
        return value in _OFF or value is False
    return value in {True, "true", "yes", "on", "remove", "hide", "omit", 1, "1"}


def walk_label_edits(value: Any, *, key: str = "") -> None:
    """Raise when a payload key or instruction would drop the mark."""

    if key and _locked_key(key, value):
        raise LabelLocked(REFUSAL)
    if isinstance(value, str):
        refuse_label_removal(value)
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            name = str(child_key)
            if _locked_key(name, child):
                raise LabelLocked(REFUSAL)
            walk_label_edits(child, key=name)
        return
    if isinstance(value, list | tuple):
        for child in value:
            walk_label_edits(child)
