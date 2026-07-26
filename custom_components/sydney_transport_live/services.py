"""Services for Sydney Transport Live."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_CLEAR_CACHE = "clear_cache"
SERVICE_PURGE_UNAVAILABLE = "purge_unavailable_trackers"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
    }
)

PURGE_SCHEMA = vol.Schema(
    {
        vol.Optional("include_unknown", default=True): cv.boolean,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _async_refresh(call: ServiceCall) -> None:
        for entry in _target_entries(hass, call.data):
            runtime = entry.runtime_data
            await runtime.position_coordinator.async_request_refresh()
            await runtime.departure_coordinator.async_request_refresh()
            _LOGGER.info("Manual refresh requested for %s", entry.title)

    async def _async_clear_cache(call: ServiceCall) -> None:
        for entry in _target_entries(hass, call.data):
            runtime = entry.runtime_data
            await runtime.static_store.async_clear_cache()
            await runtime.static_store.async_ensure_loaded(
                route_short_name=runtime.route.short_name
            )
            await runtime.position_coordinator.async_request_refresh()
            _LOGGER.info("Static GTFS cache cleared for %s", entry.title)

    async def _async_purge_unavailable(call: ServiceCall) -> None:
        """Remove leftover unavailable/unknown bus device_trackers from the registry."""
        registry = er.async_get(hass)
        include_unknown = call.data.get("include_unknown", True)
        removable_states = {STATE_UNAVAILABLE}
        if include_unknown:
            removable_states.add(STATE_UNKNOWN)

        removed = 0
        for entry in list(registry.entities.values()):
            if entry.domain != "device_tracker":
                continue
            is_ours = entry.platform == DOMAIN or (
                bool(entry.unique_id)
                and entry.unique_id.startswith(f"{DOMAIN}_bus_")
            )
            if not is_ours:
                continue

            state = hass.states.get(entry.entity_id)
            state_value = state.state if state is not None else STATE_UNAVAILABLE
            if state_value not in removable_states:
                continue

            registry.async_remove(entry.entity_id)
            removed += 1

        _LOGGER.info(
            "Purged %s unavailable/unknown Sydney Transport Live bus trackers",
            removed,
        )

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_CACHE, _async_clear_cache, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PURGE_UNAVAILABLE,
        _async_purge_unavailable,
        schema=PURGE_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when no loaded entries remain."""
    still_loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state == ConfigEntryState.LOADED
    ]
    # Called from unload of the current entry while it is still LOADED.
    if len(still_loaded) > 1:
        return

    for service in (SERVICE_REFRESH, SERVICE_CLEAR_CACHE, SERVICE_PURGE_UNAVAILABLE):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


@callback
def _target_entries(hass: HomeAssistant, data: dict[str, Any]) -> list[Any]:
    entry_id = data.get("entry_id")
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state == ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
    ]
    if entry_id:
        return [entry for entry in entries if entry.entry_id == entry_id]
    return entries
