"""Diagnostics support for Sydney Transport Live."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY

TO_REDACT = {CONF_API_KEY, "api_key", "Authorization"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    position = runtime.position_coordinator
    departure = runtime.departure_coordinator

    data = {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "route": {
            "short_name": runtime.route.short_name,
            "route_ids": sorted(runtime.route.route_ids),
            "direction_id": runtime.route.direction_id,
            "direction_label": runtime.route.direction_label,
        },
        "stop": {
            "stop_id": runtime.stop.stop_id,
            "stop_name": runtime.stop.stop_name,
            "stop_code": runtime.stop.stop_code,
            "latitude": runtime.stop.latitude,
            "longitude": runtime.stop.longitude,
        },
        "stops": [
            {
                "stop_id": s.stop_id,
                "stop_name": s.stop_name,
                "stop_code": s.stop_code,
                "direction_label": s.direction_label,
                "sensor_name": s.sensor_name,
            }
            for s in runtime.stops
        ],
        "static_gtfs": runtime.static_store.diagnostics(),
        "position_coordinator": {
            "last_update_success": position.last_update_success,
            "last_exception": str(position.last_exception) if position.last_exception else None,
            "vehicle_count": len(position.data or {}),
            "vehicle_ids": sorted((position.data or {}).keys()),
            "update_interval": (
                position.update_interval.total_seconds()
                if position.update_interval
                else None
            ),
        },
        "departure_coordinator": {
            "last_update_success": departure.last_update_success,
            "last_exception": (
                str(departure.last_exception) if departure.last_exception else None
            ),
            "stops": {
                key: [a.as_dict() for a in arrivals]
                for key, arrivals in (departure.data or {}).items()
            },
            "update_interval": (
                departure.update_interval.total_seconds()
                if departure.update_interval
                else None
            ),
        },
    }
    return async_redact_data(data, TO_REDACT)
