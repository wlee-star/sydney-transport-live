"""GTFS-Realtime vehicle position decoding."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from google.transit import gtfs_realtime_pb2

from ..models import Vehicle

if TYPE_CHECKING:
    from .static_gtfs import GtfsStaticStore
    from ..models import RouteConfig

_LOGGER = logging.getLogger(__name__)

_OCCUPANCY_NAMES = {
    0: "empty",
    1: "many_seats_available",
    2: "few_seats_available",
    3: "standing_room_only",
    4: "crushed_standing_room_only",
    5: "full",
    6: "not_accepting_passengers",
}

_STOP_STATUS_NAMES = {
    0: "incoming_at",
    1: "stopped_at",
    2: "in_transit_to",
}


def parse_vehicle_positions(
    payload: bytes,
    *,
    route: RouteConfig,
    static_store: GtfsStaticStore,
) -> dict[str, Vehicle]:
    """Decode a GTFS-R FeedMessage and return filtered vehicles."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)

    vehicles: dict[str, Vehicle] = {}
    total = 0
    matched = 0

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        total += 1
        vp = entity.vehicle
        trip = vp.trip if vp.HasField("trip") else None

        route_id = trip.route_id if trip and trip.route_id else None
        trip_id = trip.trip_id if trip and trip.trip_id else None
        direction_id: int | None = None
        headsign: str | None = None
        route_short = route.short_name

        if trip is not None and trip.HasField("direction_id"):
            direction_id = int(trip.direction_id)

        trip_info = static_store.get_trip(trip_id) if trip_id else None
        if trip_info is not None:
            route_id = route_id or trip_info.route_id
            if direction_id is None:
                direction_id = trip_info.direction_id
            headsign = trip_info.headsign
            if trip_info.route_short_name:
                route_short = trip_info.route_short_name

        if not _matches_route(route, route_id, route_short, static_store):
            continue
        if not _matches_direction(route, direction_id, headsign, static_store, trip_id):
            continue

        if not vp.HasField("position"):
            continue
        lat = vp.position.latitude
        lon = vp.position.longitude
        if lat == 0.0 and lon == 0.0:
            continue

        vehicle_id = _vehicle_id(vp, entity.id)
        if not vehicle_id:
            continue

        bearing = vp.position.bearing if vp.position.HasField("bearing") else None
        speed = vp.position.speed if vp.position.HasField("speed") else None
        occupancy = None
        if vp.HasField("occupancy_status"):
            occupancy = _OCCUPANCY_NAMES.get(int(vp.occupancy_status), str(vp.occupancy_status))
        stop_status = None
        if vp.HasField("current_status"):
            stop_status = _STOP_STATUS_NAMES.get(int(vp.current_status), str(vp.current_status))

        ts = None
        if vp.HasField("timestamp") and vp.timestamp:
            ts = datetime.fromtimestamp(vp.timestamp, tz=UTC)

        label = None
        if vp.HasField("vehicle"):
            label = vp.vehicle.label or vp.vehicle.license_plate or None

        vehicles[vehicle_id] = Vehicle(
            vehicle_id=vehicle_id,
            latitude=float(lat),
            longitude=float(lon),
            route=route_short,
            trip_id=trip_id,
            route_id=route_id,
            direction_id=direction_id,
            destination=headsign,
            bearing=float(bearing) if bearing is not None else None,
            speed=float(speed) if speed is not None else None,
            occupancy=occupancy,
            stop_status=stop_status,
            label=label,
            timestamp=ts,
        )
        matched += 1

    _LOGGER.debug(
        "Vehicle feed: %s entities, %s matched route=%s direction=%s",
        total,
        matched,
        route.short_name,
        route.direction_id,
    )
    if total and matched == 0:
        _LOGGER.warning(
            "No vehicles matched route=%s (route_ids=%s). Check static GTFS / direction filter.",
            route.short_name,
            sorted(route.route_ids)[:5],
        )
    return vehicles


def _vehicle_id(vp: object, entity_id: str) -> str | None:
    if hasattr(vp, "vehicle") and vp.HasField("vehicle"):  # type: ignore[attr-defined]
        vid = vp.vehicle.id or vp.vehicle.label or vp.vehicle.license_plate  # type: ignore[attr-defined]
        if vid:
            return str(vid)
    if entity_id:
        return str(entity_id)
    return None


def _matches_route(
    route: RouteConfig,
    route_id: str | None,
    route_short: str | None,
    static_store: GtfsStaticStore,
) -> bool:
    if route.route_ids and route_id and route_id in route.route_ids:
        return True
    if route_short and route_short.upper() == route.short_name.upper():
        return True
    if route_id and static_store.route_short_name(route_id) == route.short_name:
        return True
    return False


def _matches_direction(
    route: RouteConfig,
    direction_id: int | None,
    headsign: str | None,
    static_store: GtfsStaticStore,
    trip_id: str | None,
) -> bool:
    if route.direction_id is None:
        return True
    if direction_id is not None:
        return direction_id == route.direction_id
    # Fall back to headsign heuristics if direction missing from feed.
    if headsign and static_store.headsign_matches_direction(headsign, route.direction_label):
        return True
    if trip_id:
        info = static_store.get_trip(trip_id)
        if info and info.direction_id is not None:
            return info.direction_id == route.direction_id
    # If we cannot determine direction, include the vehicle (better than empty map).
    return direction_id is None
