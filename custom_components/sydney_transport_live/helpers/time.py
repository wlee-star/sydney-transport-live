"""Time helpers for Australia/Sydney."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def now_sydney() -> datetime:
    """Current time in Australia/Sydney."""
    return datetime.now(SYDNEY_TZ)


def minutes_until(when: datetime | None, *, now: datetime | None = None) -> int | None:
    """Whole minutes from now until when (floored, never negative)."""
    if when is None:
        return None
    current = now or now_sydney()
    if when.tzinfo is None:
        when = when.replace(tzinfo=SYDNEY_TZ)
    delta = when - current
    return max(0, int(delta.total_seconds() // 60))
