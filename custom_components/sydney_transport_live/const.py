"""Constants for Sydney Transport Live."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "sydney_transport_live"
MANUFACTURER: Final = "Transport for NSW"
ATTRIBUTION: Final = "Data provided by Transport for NSW"

API_BASE: Final = "https://api.transport.nsw.gov.au"

# Endpoints (relative to API_BASE)
ENDPOINT_VEHICLE_POS: Final = "/v1/gtfs/vehiclepos/buses"
ENDPOINT_TRIP_UPDATES: Final = "/v1/gtfs/realtime/buses"
ENDPOINT_STATIC_GTFS: Final = "/v1/gtfs/schedule/buses"
ENDPOINT_DEPARTURE_MON: Final = "/v1/tp/departure_mon"
ENDPOINT_STOP_FINDER: Final = "/v1/tp/stop_finder"

DEFAULT_ROUTE_SHORT_NAME: Final = "311"
DEFAULT_STOP_NAME: Final = "Macleay St at Rockwall Cres"
DEFAULT_DIRECTION_LABEL: Final = "Sydney CBD"

# Curated stop seeds for Potts Point (stop_id filled/confirmed from static GTFS).
# "At Rockwall Cres" is typically CBD-bound; "Opp" is the opposite side.
CURATED_STOPS: Final[tuple[dict[str, str], ...]] = (
    {
        # 201137 is the stop itself; 10134408 is the Trip Planner alias for it.
        # Both return the same board — do not use 201153, which is Fitzroy
        # Gardens (a different stop ~300 m south, heading the other way).
        "stop_code": "201137",
        "departure_stop_id": "10134408",
        "name": "Macleay St at Rockwall Cres",
        "hint": "Northbound / Millers Point",
        "direction_label": "→ City",
        "sensor_name": "At Rockwall Cres",
    },
    {
        "stop_code": "201152",
        "departure_stop_id": "201152",
        "name": "Macleay St Opp Rockwall Cres",
        "hint": "Opposite side of street",
        "direction_label": "→ Central",
        "sensor_name": "Opp Rockwall Cres",
    },
)

DEFAULT_POSITION_INTERVAL: Final = timedelta(seconds=8)
DEFAULT_DEPARTURE_INTERVAL: Final = timedelta(seconds=15)
MIN_POSITION_INTERVAL_SECONDS: Final = 5
MIN_DEPARTURE_INTERVAL_SECONDS: Final = 10
ETA_TICK_SECONDS: Final = 1

VEHICLE_MISS_TTL_POLLS: Final = 2
MAX_ARRIVALS: Final = 5

STATIC_GTFS_REFRESH_HOUR: Final = 3  # local ~03:00 refresh window
STATIC_CACHE_SUBDIR: Final = "sydney_transport_live/gtfs_buses"

# Config entry keys
CONF_API_KEY: Final = "api_key"
CONF_ROUTE_SHORT_NAME: Final = "route_short_name"
CONF_STOP_ID: Final = "stop_id"
CONF_STOP_CODE: Final = "stop_code"
CONF_STOP_NAME: Final = "stop_name"
CONF_DIRECTION_ID: Final = "direction_id"
CONF_DIRECTION_LABEL: Final = "direction_label"
CONF_POSITION_INTERVAL: Final = "position_interval"
CONF_DEPARTURE_INTERVAL: Final = "departure_interval"

# Entity attribute keys
ATTR_ROUTE: Final = "route"
ATTR_DESTINATION: Final = "destination"
ATTR_VEHICLE_ID: Final = "vehicle_id"
ATTR_TRIP_ID: Final = "trip_id"
ATTR_BEARING: Final = "bearing"
ATTR_SPEED: Final = "speed"
ATTR_OCCUPANCY: Final = "occupancy"
ATTR_STOP_STATUS: Final = "stop_status"
ATTR_ARRIVALS: Final = "arrivals"
ATTR_STOP_NAME: Final = "stop_name"
ATTR_DIRECTION: Final = "direction"
ATTR_VEHICLE_IDS: Final = "vehicle_ids"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_ESTIMATED_ARRIVAL: Final = "estimated_arrival"
ATTR_ATTRIBUTION: Final = "attribution"

# Headsign patterns that indicate CBD / City direction for route 311
CBD_HEADSIGN_PATTERNS: Final[tuple[str, ...]] = (
    "city",
    "millers point",
    "cbd",
    "circular quay",
    "wynyard",
    "town hall",
)

PLATFORMS: Final[tuple[str, ...]] = (
    "device_tracker",
    "sensor",
    "geo_location",
)

# Source string for Map card geo_location_sources
GEO_LOCATION_SOURCE: Final = DOMAIN

LOGGER_NAME: Final = f"custom_components.{DOMAIN}"
