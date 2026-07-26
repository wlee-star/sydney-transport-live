"""Services for Sydney Transport Live."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_CLEAR_CACHE = "clear_cache"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
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

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_CACHE, _async_clear_cache, schema=SERVICE_SCHEMA
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

    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    if hass.services.has_service(DOMAIN, SERVICE_CLEAR_CACHE):
        hass.services.async_remove(DOMAIN, SERVICE_CLEAR_CACHE)


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
