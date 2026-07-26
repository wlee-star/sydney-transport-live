"""Device tracker platform — live bus GPS entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_BEARING,
    ATTR_DESTINATION,
    ATTR_OCCUPANCY,
    ATTR_ROUTE,
    ATTR_SPEED,
    ATTR_STOP_STATUS,
    ATTR_TRIP_ID,
    ATTR_VEHICLE_ID,
)
from .coordinator import VehiclePositionCoordinator
from .entity import SydneyTransportEntity
from .helpers.entity_id import bus_unique_id
from .models import Vehicle

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dynamic bus device trackers."""
    runtime = entry.runtime_data
    coordinator: VehiclePositionCoordinator = runtime.position_coordinator
    route = runtime.route
    trackers: dict[str, SydneyBusTracker] = {}

    @callback
    def _add_vehicles(vehicle_ids: set[str]) -> None:
        new_entities: list[SydneyBusTracker] = []
        for vid in vehicle_ids:
            if vid in trackers:
                continue
            tracker = SydneyBusTracker(coordinator, route, vid)
            trackers[vid] = tracker
            new_entities.append(tracker)
        if new_entities:
            _LOGGER.debug("Adding %s bus trackers", len(new_entities))
            async_add_entities(new_entities)

    @callback
    def _remove_vehicles(vehicle_ids: set[str]) -> None:
        for vid in vehicle_ids:
            tracker = trackers.pop(vid, None)
            if tracker is not None:
                hass.async_create_task(tracker.async_remove(force_remove=True))

    entry.async_on_unload(
        coordinator.async_add_vehicle_listener(
            on_new=_add_vehicles,
            on_gone=_remove_vehicles,
        )
    )

    # Seed with vehicles already present from first refresh.
    if coordinator.data:
        _add_vehicles(set(coordinator.data))


class SydneyBusTracker(SydneyTransportEntity, TrackerEntity):
    """GPS tracker for a single active bus."""

    _attr_source_type = SourceType.GPS
    _attr_translation_key = "bus"
    _attr_icon = "mdi:bus"

    def __init__(
        self,
        coordinator: VehiclePositionCoordinator,
        route: Any,
        vehicle_id: str,
    ) -> None:
        super().__init__(coordinator, route)
        self._vehicle_id = vehicle_id
        self._attr_unique_id = bus_unique_id(vehicle_id)
        self._attr_name = f"{route.short_name} {vehicle_id}"
        self._attr_force_update = True

    @property
    def _vehicle(self) -> Vehicle | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._vehicle_id)

    @property
    def available(self) -> bool:
        return super().available and self._vehicle is not None

    @property
    def latitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle.latitude if vehicle else None

    @property
    def longitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle.longitude if vehicle else None

    @property
    def location_accuracy(self) -> int:
        return 50

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        vehicle = self._vehicle
        if vehicle is None:
            return {ATTR_VEHICLE_ID: self._vehicle_id}
        return {
            ATTR_ROUTE: vehicle.route,
            ATTR_DESTINATION: vehicle.destination,
            ATTR_VEHICLE_ID: vehicle.vehicle_id,
            ATTR_TRIP_ID: vehicle.trip_id,
            ATTR_BEARING: vehicle.bearing,
            ATTR_SPEED: vehicle.speed,
            ATTR_OCCUPANCY: vehicle.occupancy,
            ATTR_STOP_STATUS: vehicle.stop_status,
        }
