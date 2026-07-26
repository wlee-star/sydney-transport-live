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
from .assets_manager import install_map_assets
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
    CURATED_STOPS,
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
    stops: list[StopConfig]


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
    try:
        await static_store.async_ensure_loaded(route_short_name=route_short_name)
    except Exception as err:  # noqa: BLE001
        # Schedule ZIP is large; allow the integration to start and filter
        # live vehicles by route short name / route_id patterns instead.
        _LOGGER.warning(
            "Static GTFS not available yet (%s). Continuing with live-feed filters.",
            err,
        )

    marker_url = await hass.async_add_executor_job(install_map_assets, hass)
    hass.data.setdefault(DOMAIN, {})["marker_url"] = marker_url

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
            direction_label=direction_label,
            sensor_name="Next arrival",
        )
    else:
        stop = StopConfig(
            stop_id=stop_id or (stop_code or ""),
            stop_name=stop_name,
            stop_code=stop_code,
            direction_label=direction_label,
            sensor_name="Next arrival",
        )

    # Always include both Potts Point Rockwall Cres stops for the ETA timetable.
    stops: list[StopConfig] = []
    seen_codes: set[str] = set()
    for seed in CURATED_STOPS:
        code = seed["stop_code"]
        resolved = static_store.find_stop_by_code(code)
        if resolved is not None:
            stops.append(
                StopConfig(
                    stop_id=resolved.stop_id,
                    stop_name=resolved.stop_name,
                    stop_code=resolved.stop_code or code,
                    latitude=resolved.latitude,
                    longitude=resolved.longitude,
                    direction_label=seed.get("direction_label", ""),
                    sensor_name=seed.get("sensor_name", resolved.stop_name),
                )
            )
        else:
            stops.append(
                StopConfig(
                    stop_id=code,
                    stop_name=seed["name"],
                    stop_code=code,
                    direction_label=seed.get("direction_label", ""),
                    sensor_name=seed.get("sensor_name", seed["name"]),
                )
            )
        seen_codes.add(code)

    if stop.stop_code and stop.stop_code not in seen_codes:
        stops.append(stop)

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
        stops=stops,
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
        stops=stops,
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.GEO_LOCATION]
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
        entry, [Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.GEO_LOCATION]
    )
    if unload_ok:
        await async_unload_services(hass)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: SydneyTransportConfigEntry
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
