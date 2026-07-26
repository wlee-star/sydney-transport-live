"""Sydney Transport Live custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import TfnswApiClient
from .api.static_gtfs import GtfsStaticStore
from .const import (
    CONF_API_KEY,
    CONF_DEPARTURE_INTERVAL,
    CONF_DIRECTION_ID,
    CONF_DIRECTION_LABEL,
    CONF_POSITION_INTERVAL,
    CONF_ROUTE_SHORT_NAME,
    CONF_STOP_CODE,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DEFAULT_DEPARTURE_INTERVAL,
    DEFAULT_DIRECTION_LABEL,
    DEFAULT_POSITION_INTERVAL,
    DEFAULT_ROUTE_SHORT_NAME,
    DEFAULT_STOP_NAME,
    DOMAIN,
)
from .coordinator import DepartureCoordinator, VehiclePositionCoordinator
from .models import RouteConfig, StopConfig
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

type SydneyTransportConfigEntry = ConfigEntry[SydneyTransportRuntimeData]


@dataclass(slots=True)
class SydneyTransportRuntimeData:
    """Runtime objects attached to a config entry."""

    client: TfnswApiClient
    static_store: GtfsStaticStore
    position_coordinator: VehiclePositionCoordinator
    departure_coordinator: DepartureCoordinator
    route: RouteConfig
    stop: StopConfig


async def async_setup_entry(
    hass: HomeAssistant, entry: SydneyTransportConfigEntry
) -> bool:
    """Set up Sydney Transport Live from a config entry."""
    session = async_get_clientsession(hass)
    api_key: str = entry.data[CONF_API_KEY]
    client = TfnswApiClient(session=session, api_key=api_key)

    options = entry.options
    route_short_name = options.get(
        CONF_ROUTE_SHORT_NAME,
        entry.data.get(CONF_ROUTE_SHORT_NAME, DEFAULT_ROUTE_SHORT_NAME),
    )
    stop_id = options.get(CONF_STOP_ID, entry.data.get(CONF_STOP_ID, ""))
    stop_name = options.get(
        CONF_STOP_NAME, entry.data.get(CONF_STOP_NAME, DEFAULT_STOP_NAME)
    )
    stop_code = options.get(CONF_STOP_CODE, entry.data.get(CONF_STOP_CODE))
    direction_id = options.get(
        CONF_DIRECTION_ID, entry.data.get(CONF_DIRECTION_ID)
    )
    direction_label = options.get(
        CONF_DIRECTION_LABEL,
        entry.data.get(CONF_DIRECTION_LABEL, DEFAULT_DIRECTION_LABEL),
    )

    position_seconds = options.get(
        CONF_POSITION_INTERVAL, int(DEFAULT_POSITION_INTERVAL.total_seconds())
    )
    departure_seconds = options.get(
        CONF_DEPARTURE_INTERVAL, int(DEFAULT_DEPARTURE_INTERVAL.total_seconds())
    )

    static_store = GtfsStaticStore(hass=hass, client=client)
    await static_store.async_ensure_loaded(route_short_name=route_short_name)

    route_ids = static_store.route_ids_for_short_name(route_short_name)
    route = RouteConfig(
        short_name=route_short_name,
        route_ids=frozenset(route_ids),
        direction_id=int(direction_id) if direction_id is not None else None,
        direction_label=direction_label,
    )

    # Prefer resolved GTFS stop_id; fall back to stop_code lookup.
    resolved_stop = None
    if stop_id:
        resolved_stop = static_store.get_stop(stop_id)
    if resolved_stop is None and stop_code:
        resolved_stop = static_store.find_stop_by_code(stop_code)
    if resolved_stop is not None:
        stop = StopConfig(
            stop_id=resolved_stop.stop_id,
            stop_name=resolved_stop.stop_name,
            stop_code=resolved_stop.stop_code,
            latitude=resolved_stop.latitude,
            longitude=resolved_stop.longitude,
        )
    else:
        stop = StopConfig(
            stop_id=stop_id or (stop_code or ""),
            stop_name=stop_name,
            stop_code=stop_code,
        )

    position_coordinator = VehiclePositionCoordinator(
        hass=hass,
        config_entry=entry,
        client=client,
        static_store=static_store,
        route=route,
        update_interval_seconds=int(position_seconds),
    )
    departure_coordinator = DepartureCoordinator(
        hass=hass,
        config_entry=entry,
        client=client,
        route=route,
        stop=stop,
        update_interval_seconds=int(departure_seconds),
    )

    await position_coordinator.async_config_entry_first_refresh()
    await departure_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SydneyTransportRuntimeData(
        client=client,
        static_store=static_store,
        position_coordinator=position_coordinator,
        departure_coordinator=departure_coordinator,
        route=route,
        stop=stop,
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.DEVICE_TRACKER, Platform.SENSOR]
    )
    await async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(
        "Sydney Transport Live ready: route=%s stop=%s direction=%s",
        route.short_name,
        stop.stop_name,
        route.direction_label,
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SydneyTransportConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform.DEVICE_TRACKER, Platform.SENSOR]
    )
    if unload_ok:
        await async_unload_services(hass)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: SydneyTransportConfigEntry
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
