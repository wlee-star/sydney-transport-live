"""Sydney Transport Live custom integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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

# Stop codes corrected after release; arrival unique_ids embed the stop code,
# so existing entities must be re-pointed or HA orphans them and the
# replacement lands on a "_2" entity_id that dashboards do not reference.
_STOP_CODE_MIGRATIONS: dict[str, str] = {"201153": "201137"}

# Preferred dashboard entity_ids. If a prior release created `_2` duplicates,
# reclaim the original names so Lovelace cards keep working.
_PREFERRED_ARRIVAL_ENTITY_IDS = (
    "sensor.route_311_at_rockwall_cres",
    "sensor.route_311_opp_rockwall_cres",
)

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
    try:
        _async_migrate_stop_code_unique_ids(hass, entry)
        _async_reclaim_arrival_entity_ids(hass, entry)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Entity registry migration skipped: %s", err)

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

    marker_urls = await hass.async_add_executor_job(install_map_assets, hass)
    hass.data.setdefault(DOMAIN, {})["marker_urls"] = marker_urls

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
        # Curated IDs are verified against the live departure board, so only
        # fall back to the fuzzy name lookup when a seed has none.
        departure_stop_id = seed.get("departure_stop_id")
        if not departure_stop_id:
            departure_stop_id = await _async_resolve_departure_stop_id(
                client, seed["name"]
            )
        if resolved is not None:
            stops.append(
                StopConfig(
                    stop_id=resolved.stop_id,
                    stop_name=resolved.stop_name,
                    stop_code=resolved.stop_code or code,
                    departure_stop_id=departure_stop_id,
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
                    departure_stop_id=departure_stop_id,
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

    # Use async_refresh (not async_config_entry_first_refresh) so a temporary
    # TfNSW failure — especially the large vehiclepos download — cannot abort
    # setup and leave sensors stuck as restored/unavailable shells.
    await departure_coordinator.async_refresh()
    await position_coordinator.async_refresh()
    if not departure_coordinator.last_update_success:
        _LOGGER.warning(
            "Initial departure fetch failed; sensors will retry on the next poll"
        )
    if not position_coordinator.last_update_success:
        _LOGGER.warning(
            "Initial vehicle position fetch failed; map pins will retry on the next poll"
        )

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


@callback
def _async_migrate_stop_code_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Re-point arrival entities whose stop code was corrected after release.

    Keeps the original entity_id (and its history) so existing dashboards
    referencing it keep working.
    """
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)

    for old_code, new_code in _STOP_CODE_MIGRATIONS.items():
        old_fragment = f"_arrival_{old_code}_"
        new_fragment = f"_arrival_{new_code}_"
        for reg_entry in entries:
            if old_fragment not in reg_entry.unique_id:
                continue
            new_unique_id = reg_entry.unique_id.replace(old_fragment, new_fragment)

            # A previous startup may already have created the replacement under
            # a suffixed entity_id. Drop it so the original can be reclaimed.
            duplicate = registry.async_get_entity_id(
                reg_entry.domain, reg_entry.platform, new_unique_id
            )
            if duplicate == reg_entry.entity_id:
                continue
            if duplicate is not None:
                _LOGGER.info(
                    "Removing duplicate arrival entity %s so %s can keep its ID",
                    duplicate,
                    reg_entry.entity_id,
                )
                registry.async_remove(duplicate)

            _LOGGER.info(
                "Migrating %s unique_id %s -> %s",
                reg_entry.entity_id,
                reg_entry.unique_id,
                new_unique_id,
            )
            registry.async_update_entity(
                reg_entry.entity_id, new_unique_id=new_unique_id
            )


@callback
def _async_reclaim_arrival_entity_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Rename sensor.*_2 arrivals back onto the dashboard entity_ids.

    After the stop-code unique_id change, HA often created
    ``sensor.route_311_at_rockwall_cres_2`` while leaving the original id as a
    restored/unavailable shell. Dashboards still point at the original id.
    """
    registry = er.async_get(hass)
    owned = {
        reg.entity_id: reg
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    for preferred in _PREFERRED_ARRIVAL_ENTITY_IDS:
        suffixed = f"{preferred}_2"
        live = owned.get(suffixed)
        if live is None:
            continue

        shell = owned.get(preferred)
        if shell is not None:
            _LOGGER.info(
                "Removing restored arrival shell %s so %s can reclaim that id",
                preferred,
                suffixed,
            )
            registry.async_remove(preferred)

        _LOGGER.info("Reclaiming arrival entity_id %s -> %s", suffixed, preferred)
        registry.async_update_entity(suffixed, new_entity_id=preferred)


async def _async_resolve_departure_stop_id(
    client: TfnswApiClient,
    stop_name: str,
    fallback: str | None = None,
) -> str | None:
    """Resolve a human stop name to the Trip Planner stop ID.

    GTFS stop codes and Trip Planner's departure-monitor IDs are not reliably
    interchangeable. Resolve from TfNSW at startup so arrivals use the same
    identifier as the official departures page.
    """
    try:
        locations = await client.async_find_stops(stop_name)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not resolve Trip Planner stop %s: %s", stop_name, err)
        return fallback

    expected = _normalise_stop_name(stop_name)
    best: dict[str, object] | None = None
    for location in locations:
        name = str(
            location.get("name")
            or location.get("disassembledName")
            or location.get("label")
            or ""
        )
        if _normalise_stop_name(name) == expected:
            best = location
            break
        if best is None and expected in _normalise_stop_name(name):
            best = location

    if best is None:
        return fallback
    for key in ("id", "stopId", "assignedStopId"):
        value = best.get(key)
        if value:
            return str(value)
    return fallback


def _normalise_stop_name(value: str) -> str:
    """Compare common TfNSW stop naming variants."""
    return (
        value.lower()
        .replace("street", "st")
        .replace("opposite", "opp")
        .replace(",", "")
        .replace(".", "")
        .replace(" ", "")
    )
