"""Shared entity base for Sydney Transport Live."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import DepartureCoordinator, VehiclePositionCoordinator
from .models import RouteConfig


def route_device_info(route: RouteConfig) -> DeviceInfo:
    """Device registry entry grouping route entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"route_{route.short_name}")},
        name=f"Route {route.short_name}",
        manufacturer=MANUFACTURER,
        model="Sydney Bus",
        configuration_url="https://opendata.transport.nsw.gov.au/",
    )


class SydneyTransportEntity(CoordinatorEntity[VehiclePositionCoordinator | DepartureCoordinator]):
    """Base entity with common attribution and device info."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: VehiclePositionCoordinator | DepartureCoordinator,
        route: RouteConfig,
    ) -> None:
        super().__init__(coordinator)
        self._route = route
        self._attr_device_info = route_device_info(route)
