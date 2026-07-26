"""Static GTFS download, cache, and indexing."""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from ..const import (
    CBD_HEADSIGN_PATTERNS,
    CURATED_STOPS,
    DEFAULT_DIRECTION_LABEL,
    STATIC_CACHE_SUBDIR,
    STATIC_GTFS_REFRESH_HOUR,
)
from ..models import StopInfo, TripInfo
from .client import TfnswApiClient

_LOGGER = logging.getLogger(__name__)
_SYDNEY = ZoneInfo("Australia/Sydney")


class GtfsStaticStore:
    """Download and index the TfNSW buses static GTFS bundle."""

    def __init__(self, hass: HomeAssistant, client: TfnswApiClient) -> None:
        self._hass = hass
        self._client = client
        self._cache_dir = Path(hass.config.path(STATIC_CACHE_SUBDIR))
        self._zip_path = self._cache_dir / "buses.zip"
        self._meta_path = self._cache_dir / "meta.json"

        self._route_short_to_ids: dict[str, set[str]] = {}
        self._route_id_to_short: dict[str, str] = {}
        self._trips: dict[str, TripInfo] = {}
        self._stops_by_id: dict[str, StopInfo] = {}
        self._stops_by_code: dict[str, StopInfo] = {}
        self._loaded_routes: set[str] = set()
        self._last_loaded: datetime | None = None

    @property
    def last_loaded(self) -> datetime | None:
        """When static data was last loaded into memory."""
        return self._last_loaded

    async def async_ensure_loaded(self, *, route_short_name: str) -> None:
        """Ensure ZIP is on disk and indexes for the route are ready."""
        await self._hass.async_add_executor_job(self._cache_dir.mkdir, True, True)
        needs_download = await self._hass.async_add_executor_job(self._needs_download)
        if needs_download:
            _LOGGER.info("Downloading TfNSW buses static GTFS bundle")
            payload = await self._client.async_get_static_gtfs()
            await self._hass.async_add_executor_job(self._write_zip, payload)

        await self._hass.async_add_executor_job(
            self._index_from_zip, route_short_name
        )
        self._last_loaded = datetime.now(_SYDNEY)

    async def async_clear_cache(self) -> None:
        """Delete cached ZIP and force re-download next load."""
        def _clear() -> None:
            if self._zip_path.exists():
                self._zip_path.unlink()
            if self._meta_path.exists():
                self._meta_path.unlink()

        await self._hass.async_add_executor_job(_clear)
        self._route_short_to_ids.clear()
        self._route_id_to_short.clear()
        self._trips.clear()
        self._stops_by_id.clear()
        self._stops_by_code.clear()
        self._loaded_routes.clear()
        self._last_loaded = None

    def route_ids_for_short_name(self, short_name: str) -> set[str]:
        """Return GTFS route_id values for a public route number."""
        return set(self._route_short_to_ids.get(short_name.upper(), set()))

    def route_short_name(self, route_id: str) -> str | None:
        """Map route_id back to short name."""
        return self._route_id_to_short.get(route_id)

    def get_trip(self, trip_id: str | None) -> TripInfo | None:
        """Look up trip metadata."""
        if not trip_id:
            return None
        return self._trips.get(trip_id)

    def get_stop(self, stop_id: str) -> StopInfo | None:
        """Look up stop by GTFS stop_id."""
        return self._stops_by_id.get(stop_id)

    def find_stop_by_code(self, stop_code: str) -> StopInfo | None:
        """Look up stop by public stop code."""
        return self._stops_by_code.get(stop_code)

    def find_stops_matching(self, query: str) -> list[StopInfo]:
        """Simple name/code search for config flow."""
        q = query.lower().strip()
        results: list[StopInfo] = []
        for stop in self._stops_by_id.values():
            hay = f"{stop.stop_name} {stop.stop_code or ''} {stop.stop_id}".lower()
            if q in hay:
                results.append(stop)
        results.sort(key=lambda s: s.stop_name)
        return results[:25]

    def curated_stops(self) -> list[StopInfo]:
        """Resolve curated Potts Point stops from the index."""
        found: list[StopInfo] = []
        for seed in CURATED_STOPS:
            stop = None
            code = seed.get("stop_code")
            if code:
                stop = self.find_stop_by_code(code)
            if stop is None:
                # Fuzzy name match
                matches = self.find_stops_matching(seed["name"])
                stop = matches[0] if matches else None
            if stop is not None:
                found.append(stop)
            else:
                found.append(
                    StopInfo(
                        stop_id=code or seed["name"],
                        stop_name=seed["name"],
                        stop_code=code,
                    )
                )
        return found

    def direction_choices_for_route(
        self, route_short_name: str
    ) -> list[tuple[int, str]]:
        """Return (direction_id, label) pairs inferred from trip headsigns."""
        route_ids = self.route_ids_for_short_name(route_short_name)
        buckets: dict[int, list[str]] = {}
        for trip in self._trips.values():
            if trip.route_id not in route_ids:
                continue
            if trip.direction_id is None:
                continue
            buckets.setdefault(trip.direction_id, [])
            if trip.headsign:
                buckets[trip.direction_id].append(trip.headsign)

        choices: list[tuple[int, str]] = []
        for direction_id, headsigns in sorted(buckets.items()):
            label = self._label_for_headsigns(headsigns, direction_id)
            choices.append((direction_id, label))

        if not choices:
            choices = [
                (0, DEFAULT_DIRECTION_LABEL),
                (1, "Opposite direction"),
            ]
        return choices

    def preferred_cbd_direction_id(self, route_short_name: str) -> int | None:
        """Pick the direction_id whose headsigns look CBD-bound."""
        for direction_id, label in self.direction_choices_for_route(route_short_name):
            if self.headsign_matches_direction(label, DEFAULT_DIRECTION_LABEL):
                return direction_id
        return None

    def headsign_matches_direction(self, headsign: str, direction_label: str) -> bool:
        """Heuristic match for CBD / City direction labels."""
        text = f"{headsign} {direction_label}".lower()
        return any(p in text for p in CBD_HEADSIGN_PATTERNS)

    def diagnostics(self) -> dict[str, Any]:
        """Redacted static-store snapshot for diagnostics."""
        return {
            "cache_dir": str(self._cache_dir),
            "zip_present": self._zip_path.exists(),
            "last_loaded": self._last_loaded.isoformat() if self._last_loaded else None,
            "routes_indexed": sorted(self._loaded_routes),
            "route_count": len(self._route_id_to_short),
            "trip_count": len(self._trips),
            "stop_count": len(self._stops_by_id),
        }

    def _needs_download(self) -> bool:
        if not self._zip_path.exists():
            return True
        meta = self._read_meta()
        downloaded_at = meta.get("downloaded_at")
        if not downloaded_at:
            return True
        try:
            ts = datetime.fromisoformat(downloaded_at)
        except ValueError:
            return True
        now = datetime.now(_SYDNEY)
        # Refresh after the nightly window if the file is from a previous local day
        # and we are past STATIC_GTFS_REFRESH_HOUR.
        if ts.astimezone(_SYDNEY).date() < now.date() and now.hour >= STATIC_GTFS_REFRESH_HOUR:
            return True
        # Also refresh if older than 36 hours regardless.
        age_hours = (now - ts.astimezone(_SYDNEY)).total_seconds() / 3600
        return age_hours > 36

    def _write_zip(self, payload: bytes) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._zip_path.write_bytes(payload)
        meta = {
            "downloaded_at": datetime.now(_SYDNEY).isoformat(),
            "size_bytes": len(payload),
        }
        self._meta_path.write_text(json.dumps(meta), encoding="utf-8")
        _LOGGER.info("Saved static GTFS ZIP (%s bytes)", len(payload))

    def _read_meta(self) -> dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _index_from_zip(self, route_short_name: str) -> None:
        """Parse routes/trips/stops needed for the configured route."""
        if not self._zip_path.exists():
            raise FileNotFoundError(f"Missing GTFS cache at {self._zip_path}")

        short_key = route_short_name.upper()
        with zipfile.ZipFile(self._zip_path, "r") as zf:
            names = {name.split("/")[-1].lower(): name for name in zf.namelist()}

            # Routes
            route_ids: set[str] = set()
            routes_name = names.get("routes.txt")
            if routes_name:
                with zf.open(routes_name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    for row in reader:
                        rid = (row.get("route_id") or "").strip()
                        rshort = (row.get("route_short_name") or "").strip()
                        if not rid or not rshort:
                            continue
                        self._route_id_to_short[rid] = rshort
                        self._route_short_to_ids.setdefault(rshort.upper(), set()).add(rid)
                        if rshort.upper() == short_key:
                            route_ids.add(rid)

            # Trips — only for matched route ids (never scan the entire network)
            trips_name = names.get("trips.txt")
            if trips_name and route_ids:
                # Drop previous trips for this route so re-index stays fresh
                stale = [
                    tid
                    for tid, info in self._trips.items()
                    if info.route_short_name
                    and info.route_short_name.upper() == short_key
                ]
                for tid in stale:
                    self._trips.pop(tid, None)

                with zf.open(trips_name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    for row in reader:
                        rid = (row.get("route_id") or "").strip()
                        if rid not in route_ids:
                            continue
                        trip_id = (row.get("trip_id") or "").strip()
                        if not trip_id:
                            continue
                        direction_raw = (row.get("direction_id") or "").strip()
                        direction_id = (
                            int(direction_raw) if direction_raw.isdigit() else None
                        )
                        headsign = (row.get("trip_headsign") or "").strip() or None
                        self._trips[trip_id] = TripInfo(
                            trip_id=trip_id,
                            route_id=rid,
                            direction_id=direction_id,
                            headsign=headsign,
                            route_short_name=self._route_id_to_short.get(rid),
                        )

            # Stops — index all for config-flow search (buses stop file is manageable)
            stops_name = names.get("stops.txt")
            if stops_name and not self._stops_by_id:
                with zf.open(stops_name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    for row in reader:
                        sid = (row.get("stop_id") or "").strip()
                        if not sid:
                            continue
                        sname = (row.get("stop_name") or sid).strip()
                        scode = (row.get("stop_code") or "").strip() or None
                        lat = _float_or_none(row.get("stop_lat"))
                        lon = _float_or_none(row.get("stop_lon"))
                        info = StopInfo(
                            stop_id=sid,
                            stop_name=sname,
                            stop_code=scode,
                            latitude=lat,
                            longitude=lon,
                        )
                        self._stops_by_id[sid] = info
                        if scode:
                            self._stops_by_code[scode] = info

        self._loaded_routes.add(short_key)
        _LOGGER.info(
            "Indexed GTFS for route %s: %s route_ids, %s trips, %s stops",
            route_short_name,
            len(route_ids),
            len(self._trips),
            len(self._stops_by_id),
        )


def _float_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def async_resolve_route_defaults(
    hass: HomeAssistant,
    client: TfnswApiClient,
    route_short_name: str,
) -> dict[str, Any]:
    """Helper for config flow: load static GTFS and return curated defaults."""
    store = GtfsStaticStore(hass, client)
    await store.async_ensure_loaded(route_short_name=route_short_name)
    directions = store.direction_choices_for_route(route_short_name)
    preferred = store.preferred_cbd_direction_id(route_short_name)
    stops = store.curated_stops()
    return {
        "store": store,
        "route_ids": sorted(store.route_ids_for_short_name(route_short_name)),
        "directions": directions,
        "preferred_direction_id": preferred if preferred is not None else (
            directions[0][0] if directions else 0
        ),
        "curated_stops": stops,
    }
