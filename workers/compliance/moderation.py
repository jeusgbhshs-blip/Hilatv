"""How N16 reads a content-safety result.

A live moderator that errors, is missing, or comes back as the mock adapter is
unreviewed. That blocks delivery. Mock mode may still run the mock adapter for
tests, but the result is marked mock and is not a live clearance. Frames and
audio are not sent to a moderator here, so they stay 「画面/声音未审」.
"""

from __future__ import annotations

import os
from typing import Any

FRAME_AUDIO_STATUS = "画面/声音未审"


def live_mode() -> bool:
    return os.getenv("HILATV_LIVE", "0").strip() == "1"


def classify(safety: dict[str, Any] | None) -> str:
    """``live_pass``, ``mock``, ``blocked``, or ``unreviewed``."""

    if not isinstance(safety, dict):
        return "unreviewed"
    if safety.get("unreviewed") is True:
        return "unreviewed"
    mocked = bool(safety.get("mock")) or safety.get("moderation") == "mock"
    if mocked and live_mode():
        return "unreviewed"
    if mocked:
        if safety.get("passed") is True:
            return "mock"
        return "blocked"
    if safety.get("reviewed") is True and safety.get("passed") is True:
        return "live_pass"
    if safety.get("passed") is False:
        return "blocked"
    return "unreviewed"


def blocks_delivery(kind: str) -> bool:
    """Live mock/error results block. A mock-mode text pass does not."""

    if kind in {"unreviewed", "blocked"}:
        return True
    if kind == "mock" and live_mode():
        return True
    return False


def reason_for(kind: str, safety: dict[str, Any] | None) -> str:
    if kind == "blocked":
        detail = ""
        if isinstance(safety, dict):
            detail = str(safety.get("reason") or "")
        return detail or "content safety rejected the text"
    if kind == "unreviewed":
        return "内容审核未完成，需人工复核"
    return ""
