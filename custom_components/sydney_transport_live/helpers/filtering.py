"""Filtering helpers."""

from __future__ import annotations

from typing import Literal

from ..const import CBD_HEADSIGN_PATTERNS, CENTRAL_HEADSIGN_PATTERNS

DestinationKind = Literal["city", "central", "unknown"]


def is_cbd_headsign(headsign: str | None) -> bool:
    """Return True if a trip headsign looks CBD / City bound."""
    if not headsign:
        return False
    text = headsign.lower()
    return any(pattern in text for pattern in CBD_HEADSIGN_PATTERNS)


def is_central_headsign(headsign: str | None) -> bool:
    """Return True if a trip headsign looks Central / Eddy Ave bound."""
    if not headsign:
        return False
    text = headsign.lower()
    return any(pattern in text for pattern in CENTRAL_HEADSIGN_PATTERNS)


def destination_kind(headsign: str | None) -> DestinationKind:
    """Classify a live trip headsign for map marker styling."""
    if is_cbd_headsign(headsign):
        return "city"
    if is_central_headsign(headsign):
        return "central"
    return "unknown"


def normalize_route_short_name(value: str) -> str:
    """Normalize a user-entered route number."""
    return value.strip().upper()
