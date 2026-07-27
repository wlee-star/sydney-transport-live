"""Geo-location platform — all active route buses for the Map card.

Uses ``geo_location_sources`` so the dashboard always shows every live bus
without hard-coding device_tracker entity IDs (those go stale when trips end).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BEARING,
    ATTR_DESTINATION,
    ATTR_OCCUPANCY,
    ATTR_ROUTE,
    ATTR_SPEED,
    ATTR_TRIP_ID,
    ATTR_VEHICLE_ID,
    ATTRIBUTION,
    DOMAIN,
)
from .coordinator import VehiclePositionCoordinator
from .helpers.entity_id import bus_unique_id
from .helpers.filtering import destination_kind
from .models import RouteConfig, Vehicle

_LOGGER = logging.getLogger(__name__)

# Map card: geo_location_sources: [sydney_transport_live]
SOURCE = DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dynamic geo_location entities for live buses."""
    runtime = entry.runtime_data
    coordinator: VehiclePositionCoordinator = runtime.position_coordinator
    route: RouteConfig = runtime.route
    entities: dict[str, SydneyBusGeoLocation] = {}

    @callback
    def _add_vehicles(vehicle_ids: set[str]) -> None:
        new_entities: list[SydneyBusGeoLocation] = []
        for vid in vehicle_ids:
            if vid in entities:
                continue
            entity = SydneyBusGeoLocation(coordinator, route, vid)
            entities[vid] = entity
            new_entities.append(entity)
        if new_entities:
            _LOGGER.debug("Adding %s geo_location bus entities", len(new_entities))
            async_add_entities(new_entities)

    @callback
    def _remove_vehicles(vehicle_ids: set[str]) -> None:
        for vid in vehicle_ids:
            entity = entities.pop(vid, None)
            if entity is not None:
                hass.async_create_task(entity.async_remove(force_remove=True))

    entry.async_on_unload(
        coordinator.async_add_vehicle_listener(
            on_new=_add_vehicles,
            on_gone=_remove_vehicles,
        )
    )

    if coordinator.data:
        _add_vehicles(set(coordinator.data))


class SydneyBusGeoLocation(GeolocationEvent):
    """A single live bus as a geo_location entity for the Map card."""

    _attr_has_entity_name = False
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:bus"
    _attr_should_poll = False
    _attr_source = SOURCE

    def __init__(
        self,
        coordinator: VehiclePositionCoordinator,
        route: RouteConfig,
        vehicle_id: str,
    ) -> None:
        self.coordinator = coordinator
        self._route = route
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"{bus_unique_id(vehicle_id)}_geo"
        # Spaced digits so HA map initials render as "311" (not "3").
        self._attr_name = " ".join(route.short_name)
        self._attr_force_update = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def _vehicle(self) -> Vehicle | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._vehicle_id)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._vehicle is not None

    @property
    def latitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle.latitude if vehicle else None

    @property
    def longitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle.longitude if vehicle else None

    @property
    def distance(self) -> float | None:
        """Distance is optional; Map card mainly needs lat/lon."""
        return None

    @property
    def entity_picture(self) -> str | None:
        """Direction-coded marker: aqua for City, grey for Central."""
        vehicle = self._vehicle
        if vehicle is None:
            return None
        markers = self.hass.data.get(DOMAIN, {}).get("marker_urls") or {}
        kind = destination_kind(vehicle.destination)
        if kind == "city":
            return markers.get("city") or markers.get("default")
        if kind == "central":
            return markers.get("central") or markers.get("default")
        return markers.get("default")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        vehicle = self._vehicle
        if vehicle is None:
            return {ATTR_VEHICLE_ID: self._vehicle_id, ATTR_ROUTE: self._route.short_name}
        return {
            ATTR_ROUTE: vehicle.route,
            ATTR_DESTINATION: vehicle.destination,
            ATTR_VEHICLE_ID: vehicle.vehicle_id,
            ATTR_TRIP_ID: vehicle.trip_id,
            ATTR_BEARING: vehicle.bearing,
            ATTR_SPEED: vehicle.speed,
            ATTR_OCCUPANCY: vehicle.occupancy,
        }
