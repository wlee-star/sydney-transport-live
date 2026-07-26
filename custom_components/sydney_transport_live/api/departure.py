"""Departure board parsing for TfNSW Trip Planner API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..const import MAX_ARRIVALS
from ..models import Arrival, RouteConfig

_LOGGER = logging.getLogger(__name__)
_SYDNEY = ZoneInfo("Australia/Sydney")


def parse_departures(
    payload: dict[str, Any],
    *,
    route: RouteConfig,
    max_arrivals: int = MAX_ARRIVALS,
    now: datetime | None = None,
) -> list[Arrival]:
    """Parse rapidJSON departure_mon response into Arrival models."""
    now = now or datetime.now(_SYDNEY)
    events = payload.get("stopEvents") or []
    arrivals: list[Arrival] = []

    for event in events:
        transport = event.get("transportation") or {}
        number = (
            transport.get("number")
            or (transport.get("disassembledName") or "")
            or ""
        )
        number = str(number).strip()
        if number.upper() != route.short_name.upper():
            # Also accept route short name embedded in name fields.
            name = str(transport.get("name") or "")
            if route.short_name not in name.split():
                continue

        destination = None
        dest = transport.get("destination") or {}
        if isinstance(dest, dict):
            destination = dest.get("name") or dest.get("disassembledName")
        if destination is None:
            destination = transport.get("destination") if isinstance(
                transport.get("destination"), str
            ) else None

        if route.direction_label and destination:
            # Soft filter: if label is CBD-oriented, prefer matching headsigns.
            # Do not drop when uncertain — stop itself encodes direction.
            pass

        estimated = _parse_time(
            event.get("departureTimeEstimated") or event.get("arrivalTimeEstimated")
        )
        planned = _parse_time(
            event.get("departureTimePlanned") or event.get("arrivalTimePlanned")
        )
        when = estimated or planned
        minutes = None
        if when is not None:
            delta = when - now
            minutes = max(0, int(delta.total_seconds() // 60))

        trip_id = None
        properties = transport.get("properties") or event.get("properties") or {}
        if isinstance(properties, dict):
            trip_id = properties.get("RealtimeTripId") or properties.get("tripId")

        vehicle_id = None
        location = event.get("location") or {}
        if isinstance(location, dict):
            vehicle_id = location.get("id")

        arrivals.append(
            Arrival(
                route=route.short_name,
                destination=str(destination) if destination else None,
                estimated_arrival=when,
                minutes=minutes,
                trip_id=str(trip_id) if trip_id else None,
                vehicle_id=str(vehicle_id) if vehicle_id else None,
                realtime=estimated is not None,
            )
        )

        if len(arrivals) >= max_arrivals:
            break

    arrivals.sort(key=lambda a: (a.minutes is None, a.minutes if a.minutes is not None else 9999))
    _LOGGER.debug("Parsed %s arrivals for route %s", len(arrivals), route.short_name)
    return arrivals[:max_arrivals]


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    # rapidJSON typically uses ISO-8601 with offset, e.g. 2026-07-26T20:40:00+10:00
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _LOGGER.debug("Could not parse departure time: %s", value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_SYDNEY)
    return dt
