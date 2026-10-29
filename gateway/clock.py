"""Clocks for call logs and the Asia/Shanghai budget day."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class SystemClock:
    def __init__(self, tz: str = "Asia/Shanghai") -> None:
        self._tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self._tz)


class FrozenClock:
    """Test clock. `now` must be timezone-aware."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._now = now
