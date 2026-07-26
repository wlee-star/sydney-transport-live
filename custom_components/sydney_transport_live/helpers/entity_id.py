"""Stable unique_id builders."""

from __future__ import annotations

from ..const import DOMAIN


def bus_unique_id(vehicle_id: str) -> str:
    """Unique ID for a live bus device_tracker."""
    safe = _slug(vehicle_id)
    return f"{DOMAIN}_bus_{safe}"


def arrival_unique_id(stop_id: str, route: str, direction: str | int | None) -> str:
    """Unique ID for a next-arrival sensor."""
    return f"{DOMAIN}_arrival_{_slug(stop_id)}_{_slug(route)}_{_slug(str(direction))}"


def status_unique_id(route: str) -> str:
    """Unique ID for an active-buses / route status sensor."""
    return f"{DOMAIN}_status_{_slug(route)}"


def _slug(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )
