"""Filtering helpers."""

from __future__ import annotations

from ..const import CBD_HEADSIGN_PATTERNS


def is_cbd_headsign(headsign: str | None) -> bool:
    """Return True if a trip headsign looks CBD / City bound."""
    if not headsign:
        return False
    text = headsign.lower()
    return any(pattern in text for pattern in CBD_HEADSIGN_PATTERNS)


def normalize_route_short_name(value: str) -> str:
    """Normalize a user-entered route number."""
    return value.strip().upper()
