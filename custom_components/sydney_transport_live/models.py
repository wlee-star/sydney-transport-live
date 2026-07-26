"""Data models for Sydney Transport Live."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class StopConfig:
    """Configured stop for arrivals."""

    stop_id: str
    stop_name: str
    stop_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    direction_label: str = ""
    sensor_name: str = "Next arrival"


@dataclass(slots=True)
class RouteConfig:
    """Configured route filter."""

    short_name: str
    route_ids: frozenset[str] = field(default_factory=frozenset)
    direction_id: int | None = None
    direction_label: str = "Sydney CBD"


@dataclass(slots=True)
class Vehicle:
    """A live bus vehicle position."""

    vehicle_id: str
    latitude: float
    longitude: float
    route: str
    trip_id: str | None = None
    route_id: str | None = None
    direction_id: int | None = None
    destination: str | None = None
    bearing: float | None = None
    speed: float | None = None
    occupancy: str | None = None
    stop_status: str | None = None
    label: str | None = None
    timestamp: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics / attributes."""
        return {
            "vehicle_id": self.vehicle_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "route": self.route,
            "trip_id": self.trip_id,
            "route_id": self.route_id,
            "direction_id": self.direction_id,
            "destination": self.destination,
            "bearing": self.bearing,
            "speed": self.speed,
            "occupancy": self.occupancy,
            "stop_status": self.stop_status,
            "label": self.label,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vehicle):
            return NotImplemented
        return (
            self.vehicle_id == other.vehicle_id
            and self.latitude == other.latitude
            and self.longitude == other.longitude
            and self.bearing == other.bearing
            and self.speed == other.speed
            and self.occupancy == other.occupancy
            and self.destination == other.destination
            and self.trip_id == other.trip_id
            and self.stop_status == other.stop_status
        )


@dataclass(slots=True)
class Arrival:
    """A predicted departure / arrival at a stop."""

    route: str
    destination: str | None
    estimated_arrival: datetime | None
    minutes: int | None
    seconds: int | None = None
    trip_id: str | None = None
    vehicle_id: str | None = None
    realtime: bool = False
    occupancy: str | None = None

    @property
    def eta_display(self) -> str:
        """Countdown string for dashboards (m:ss)."""
        if self.seconds is None:
            if self.minutes is None:
                return "—"
            return f"{self.minutes} min"
        total = max(0, int(self.seconds))
        mins, secs = divmod(total, 60)
        if mins >= 60:
            hours, mins = divmod(mins, 60)
            return f"{hours}h {mins:02d}m"
        return f"{mins}:{secs:02d}"

    def as_dict(self) -> dict[str, Any]:
        """Serialize for sensor attributes."""
        return {
            "route": self.route,
            "destination": self.destination,
            "estimated_arrival": (
                self.estimated_arrival.isoformat() if self.estimated_arrival else None
            ),
            "minutes": self.minutes,
            "seconds": self.seconds,
            "eta_display": self.eta_display,
            "trip_id": self.trip_id,
            "vehicle_id": self.vehicle_id,
            "realtime": self.realtime,
            "occupancy": self.occupancy,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Arrival):
            return NotImplemented
        return (
            self.route == other.route
            and self.destination == other.destination
            and self.estimated_arrival == other.estimated_arrival
            and self.minutes == other.minutes
            and self.trip_id == other.trip_id
            and self.realtime == other.realtime
        )


@dataclass(slots=True)
class TripInfo:
    """Static GTFS trip metadata used for filtering."""

    trip_id: str
    route_id: str
    direction_id: int | None
    headsign: str | None
    route_short_name: str | None = None


@dataclass(slots=True)
class StopInfo:
    """Static GTFS stop metadata."""

    stop_id: str
    stop_name: str
    stop_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
