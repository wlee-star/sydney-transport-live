"""Data update coordinators."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import TfnswApiClient
from .api.departure import parse_departures
from .api.gtfs_realtime import parse_vehicle_positions
from .api.static_gtfs import GtfsStaticStore
from .const import DOMAIN, VEHICLE_MISS_TTL_POLLS
from .exceptions import TfnswAuthError, TfnswRateLimitError
from .models import Arrival, RouteConfig, StopConfig, Vehicle

_LOGGER = logging.getLogger(__name__)


class VehiclePositionCoordinator(DataUpdateCoordinator[dict[str, Vehicle]]):
    """Poll GTFS-R vehicle positions and filter to the configured route."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        client: TfnswApiClient,
        static_store: GtfsStaticStore,
        route: RouteConfig,
        update_interval_seconds: int,
    ) -> None:
        try:
            super().__init__(
                hass,
                _LOGGER,
                config_entry=config_entry,
                name=f"{DOMAIN}_positions",
                update_interval=timedelta(seconds=update_interval_seconds),
                always_update=False,
            )
        except TypeError:
            # Older Home Assistant without config_entry / always_update kwargs.
            super().__init__(
                hass,
                _LOGGER,
                name=f"{DOMAIN}_positions",
                update_interval=timedelta(seconds=update_interval_seconds),
            )
        self.client = client
        self.static_store = static_store
        self.route = route
        self._miss_counts: dict[str, int] = {}
        self._known_ids: set[str] = set()
        self._listeners_new: list[Callable[[set[str]], None]] = []
        self._listeners_gone: list[Callable[[set[str]], None]] = []

    @callback
    def async_add_vehicle_listener(
        self,
        *,
        on_new: Callable[[set[str]], None],
        on_gone: Callable[[set[str]], None],
    ) -> Callable[[], None]:
        """Register callbacks for vehicle add/remove."""
        self._listeners_new.append(on_new)
        self._listeners_gone.append(on_gone)

        @callback
        def _remove() -> None:
            self._listeners_new.remove(on_new)
            self._listeners_gone.remove(on_gone)

        return _remove

    async def _async_update_data(self) -> dict[str, Vehicle]:
        try:
            payload = await self.client.async_get_vehicle_positions()
        except TfnswAuthError as err:
            from homeassistant.exceptions import ConfigEntryAuthFailed

            raise ConfigEntryAuthFailed(str(err)) from err
        except TfnswRateLimitError as err:
            raise UpdateFailed(
                f"Rate limited by TfNSW (retry after {err.retry_after or 60}s)"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching vehicle positions: {err}") from err

        # Nightly static refresh opportunity
        try:
            await self.static_store.async_ensure_loaded(
                route_short_name=self.route.short_name
            )
            self.route.route_ids = frozenset(
                self.static_store.route_ids_for_short_name(self.route.short_name)
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Static GTFS refresh skipped: %s", err)

        fresh = parse_vehicle_positions(
            payload, route=self.route, static_store=self.static_store
        )
        return self._apply_miss_ttl(fresh)

    def _apply_miss_ttl(self, fresh: dict[str, Vehicle]) -> dict[str, Vehicle]:
        """Keep recently-seen buses for a few missed polls to reduce flicker."""
        fresh_ids = set(fresh)
        for vid in list(self._miss_counts):
            if vid in fresh_ids:
                self._miss_counts.pop(vid, None)

        retained: dict[str, Vehicle] = dict(fresh)
        previous = self.data or {}

        for vid, vehicle in previous.items():
            if vid in fresh_ids:
                continue
            misses = self._miss_counts.get(vid, 0) + 1
            self._miss_counts[vid] = misses
            if misses <= VEHICLE_MISS_TTL_POLLS:
                retained[vid] = vehicle
            else:
                self._miss_counts.pop(vid, None)

        new_ids = set(retained) - self._known_ids
        gone_ids = self._known_ids - set(retained)
        self._known_ids = set(retained)

        if new_ids:
            for listener in list(self._listeners_new):
                listener(new_ids)
        if gone_ids:
            for listener in list(self._listeners_gone):
                listener(gone_ids)

        return retained


class DepartureCoordinator(DataUpdateCoordinator[dict[str, list[Arrival]]]):
    """Poll Trip Planner departure boards for one or more stops."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        client: TfnswApiClient,
        route: RouteConfig,
        stops: list[StopConfig],
        update_interval_seconds: int,
    ) -> None:
        try:
            super().__init__(
                hass,
                _LOGGER,
                config_entry=config_entry,
                name=f"{DOMAIN}_departures",
                update_interval=timedelta(seconds=update_interval_seconds),
                always_update=False,
            )
        except TypeError:
            super().__init__(
                hass,
                _LOGGER,
                name=f"{DOMAIN}_departures",
                update_interval=timedelta(seconds=update_interval_seconds),
            )
        self.client = client
        self.route = route
        self.stops = stops

    async def _async_update_data(self) -> dict[str, list[Arrival]]:
        if not self.stops:
            raise UpdateFailed("No stops configured for departures")

        results: dict[str, list[Arrival]] = {}
        errors: list[str] = []

        for stop in self.stops:
            key = stop.stop_code or stop.stop_id
            if not key:
                continue
            refs: list[str] = []
            for candidate in (stop.stop_code, stop.stop_id):
                if candidate and candidate not in refs:
                    refs.append(candidate)
            if not refs:
                continue

            parsed: list[Arrival] = []
            last_err: Exception | None = None
            for stop_ref in refs:
                try:
                    payload = await self.client.async_get_departures(stop_ref)
                    parsed = parse_departures(payload, route=self.route)
                    if parsed or payload.get("stopEvents"):
                        # Keep first successful board (even if no 311 matched).
                        break
                except TfnswAuthError as err:
                    from homeassistant.exceptions import ConfigEntryAuthFailed

                    raise ConfigEntryAuthFailed(str(err)) from err
                except TfnswRateLimitError as err:
                    raise UpdateFailed(
                        f"Rate limited by TfNSW (retry after {err.retry_after or 60}s)"
                    ) from err
                except Exception as err:  # noqa: BLE001
                    last_err = err
                    _LOGGER.warning(
                        "Departure fetch failed for stop %s: %s", stop_ref, err
                    )

            if last_err and not parsed and key not in results:
                errors.append(f"{key}: {last_err}")
            results[key] = parsed

        if not results and errors:
            raise UpdateFailed(f"Error fetching departures: {'; '.join(errors)}")
        return results
