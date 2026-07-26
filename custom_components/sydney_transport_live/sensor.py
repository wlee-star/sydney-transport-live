"""Sensor platform — next arrivals and active bus count."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    ATTR_ARRIVALS,
    ATTR_DIRECTION,
    ATTR_ESTIMATED_ARRIVAL,
    ATTR_LAST_UPDATE,
    ATTR_ROUTE,
    ATTR_STOP_NAME,
    ATTR_VEHICLE_IDS,
)
from .coordinator import DepartureCoordinator, VehiclePositionCoordinator
from .entity import SydneyTransportEntity
from .helpers.entity_id import arrival_unique_id, status_unique_id
from .models import Arrival, RouteConfig, StopConfig


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up arrival and status sensors."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        ActiveBusesSensor(
            runtime.position_coordinator,
            runtime.route,
        )
    ]
    for stop in runtime.stops:
        entities.append(
            NextArrivalSensor(
                runtime.departure_coordinator,
                runtime.route,
                stop,
            )
        )
    async_add_entities(entities)


class NextArrivalSensor(SydneyTransportEntity, SensorEntity):
    """Minutes until the next matching departure at a stop."""

    _attr_translation_key = "next_arrival"
    _attr_icon = "mdi:bus-clock"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DepartureCoordinator,
        route: RouteConfig,
        stop: StopConfig,
    ) -> None:
        super().__init__(coordinator, route)
        self._stop = stop
        self._stop_key = stop.stop_code or stop.stop_id
        self._attr_unique_id = arrival_unique_id(
            self._stop_key or "unknown",
            route.short_name,
            stop.direction_label or stop.sensor_name or "all",
        )
        self._attr_name = stop.sensor_name or stop.stop_name or "Next arrival"
        self._attr_suggested_display_precision = 0

    def _arrivals(self) -> list[Arrival]:
        data = self.coordinator.data or {}
        return list(data.get(self._stop_key, []))

    @property
    def native_value(self) -> StateType:
        arrivals = self._arrivals()
        if not arrivals:
            return None
        return arrivals[0].minutes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        arrivals = self._arrivals()
        first = arrivals[0] if arrivals else None
        last_update = None
        if self.coordinator.last_update_success and self.coordinator.last_update_success_time:
            last_update = self.coordinator.last_update_success_time.isoformat()
        return {
            ATTR_ROUTE: self._route.short_name,
            ATTR_STOP_NAME: self._stop.stop_name,
            ATTR_DIRECTION: self._stop.direction_label or self._route.direction_label,
            ATTR_ESTIMATED_ARRIVAL: (
                first.estimated_arrival.isoformat()
                if first and first.estimated_arrival
                else None
            ),
            ATTR_ARRIVALS: [a.as_dict() for a in arrivals],
            "eta_summary": ", ".join(
                f"{a.minutes} min" for a in arrivals[:3] if a.minutes is not None
            ),
            ATTR_LAST_UPDATE: last_update,
        }


class ActiveBusesSensor(SydneyTransportEntity, SensorEntity):
    """Count of currently tracked buses on the route."""

    _attr_translation_key = "active_buses"
    _attr_icon = "mdi:bus-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name = "Active buses"

    def __init__(
        self,
        coordinator: VehiclePositionCoordinator,
        route: RouteConfig,
    ) -> None:
        super().__init__(coordinator, route)
        self._attr_unique_id = status_unique_id(route.short_name)

    @property
    def native_value(self) -> StateType:
        return len(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        last_update = None
        if self.coordinator.last_update_success_time:
            last_update = self.coordinator.last_update_success_time.isoformat()
        return {
            ATTR_ROUTE: self._route.short_name,
            ATTR_DIRECTION: self._route.direction_label,
            ATTR_VEHICLE_IDS: sorted(data.keys()),
            ATTR_LAST_UPDATE: last_update,
        }
