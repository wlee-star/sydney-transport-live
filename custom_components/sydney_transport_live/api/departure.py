"""Departure board parsing for TfNSW Trip Planner API."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..const import MAX_ARRIVALS
from ..models import Arrival, RouteConfig

_LOGGER = logging.getLogger(__name__)
_SYDNEY = ZoneInfo("Australia/Sydney")
_ROUTE_TOKEN = re.compile(r"\b(\d+[A-Za-z]?)\b")


def parse_departures(
    payload: dict[str, Any],
    *,
    route: RouteConfig,
    max_arrivals: int = MAX_ARRIVALS,
    now: datetime | None = None,
) -> list[Arrival]:
    """Parse rapidJSON departure_mon response into Arrival models."""
    now = now or datetime.now(_SYDNEY)
    if payload.get("error") or payload.get("errorMessages"):
        _LOGGER.warning(
            "Departure API error payload: %s",
            payload.get("error") or payload.get("errorMessages"),
        )

    events = payload.get("stopEvents") or []
    if not events:
        _LOGGER.info(
            "No stopEvents in departure payload (keys=%s)",
            list(payload.keys()),
        )
        return []

    arrivals: list[Arrival] = []
    seen_numbers: set[str] = set()

    for event in events:
        transport = event.get("transportation") or {}
        number = _route_number(transport)
        if number:
            seen_numbers.add(number)
        if not _matches_route(number, transport, route.short_name):
            continue

        destination = None
        dest = transport.get("destination") or {}
        if isinstance(dest, dict):
            destination = dest.get("name") or dest.get("disassembledName")
        elif isinstance(dest, str):
            destination = dest

        estimated = _parse_time(
            event.get("departureTimeEstimated") or event.get("arrivalTimeEstimated")
        )
        planned = _parse_time(
            event.get("departureTimePlanned") or event.get("arrivalTimePlanned")
        )
        when = estimated or planned
        seconds, minutes = _remaining(when, now)

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
                seconds=seconds,
                trip_id=str(trip_id) if trip_id else None,
                vehicle_id=str(vehicle_id) if vehicle_id else None,
                realtime=estimated is not None,
            )
        )

    arrivals.sort(
        key=lambda a: (
            a.seconds is None,
            a.seconds if a.seconds is not None else 10**9,
        )
    )
    if not arrivals:
        _LOGGER.info(
            "No %s departures matched; sample route numbers=%s (events=%s)",
            route.short_name,
            sorted(seen_numbers)[:20],
            len(events),
        )
    else:
        _LOGGER.debug(
            "Parsed %s arrivals for route %s", len(arrivals), route.short_name
        )
    return arrivals[:max_arrivals]


def refresh_arrival_countdowns(
    arrivals: list[Arrival], *, now: datetime | None = None
) -> list[Arrival]:
    """Recompute minutes/seconds from estimated_arrival timestamps."""
    now = now or datetime.now(_SYDNEY)
    refreshed: list[Arrival] = []
    for arrival in arrivals:
        seconds, minutes = _remaining(arrival.estimated_arrival, now)
        refreshed.append(
            Arrival(
                route=arrival.route,
                destination=arrival.destination,
                estimated_arrival=arrival.estimated_arrival,
                minutes=minutes,
                seconds=seconds,
                trip_id=arrival.trip_id,
                vehicle_id=arrival.vehicle_id,
                realtime=arrival.realtime,
                occupancy=arrival.occupancy,
            )
        )
    refreshed.sort(
        key=lambda a: (
            a.seconds is None,
            a.seconds if a.seconds is not None else 10**9,
        )
    )
    return refreshed


def format_eta(seconds: int | None, minutes: int | None = None) -> str:
    """Human ETA like 4:32 or 12 min."""
    if seconds is None:
        if minutes is None:
            return "—"
        return f"{minutes} min"
    if seconds < 0:
        seconds = 0
    mins, secs = divmod(int(seconds), 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}h {mins:02d}m"
    return f"{mins}:{secs:02d}"


def _remaining(
    when: datetime | None, now: datetime
) -> tuple[int | None, int | None]:
    if when is None:
        return None, None
    total = int((when - now).total_seconds())
    total = max(0, total)
    return total, total // 60


def _route_number(transport: dict[str, Any]) -> str:
    raw = transport.get("number")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    for key in ("disassembledName", "name", "description"):
        value = transport.get(key)
        if not value:
            continue
        match = _ROUTE_TOKEN.search(str(value))
        if match:
            return match.group(1)
    return ""


def _matches_route(number: str, transport: dict[str, Any], route_short: str) -> bool:
    target = route_short.strip().upper()
    if number and number.upper() == target:
        return True
    # Fallback: token match in name fields (e.g. "Bus 311 to City")
    blob = " ".join(
        str(transport.get(k) or "")
        for k in ("number", "disassembledName", "name", "description")
    ).upper()
    return bool(re.search(rf"\b{re.escape(target)}\b", blob))


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
    return dt.astimezone(_SYDNEY)
