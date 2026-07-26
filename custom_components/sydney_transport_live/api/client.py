"""HTTP client for Transport for NSW Open Data APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp

from ..const import (
    API_BASE,
    ENDPOINT_DEPARTURE_MON,
    ENDPOINT_STATIC_GTFS,
    ENDPOINT_STOP_FINDER,
    ENDPOINT_VEHICLE_POS,
)
from ..exceptions import TfnswApiError, TfnswAuthError, TfnswRateLimitError

_LOGGER = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({502, 503, 504})
_MAX_RETRIES = 2
_BACKOFF = (1.0, 3.0)


class TfnswApiClient:
    """Async TfNSW API client with retries and auth handling."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        api_base: str = API_BASE,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"apikey {self._api_key}",
            "Accept": "application/octet-stream, application/json, */*",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self._api_base}{path}"

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
        expect_json: bool = False,
    ) -> bytes | dict[str, Any] | list[Any]:
        """Perform a GET with retries for transient failures."""
        url = self._url(path)
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(timeout):
                    async with self._session.get(
                        url,
                        headers=self._headers,
                        params=params,
                    ) as response:
                        if response.status in (401, 403):
                            raise TfnswAuthError(
                                f"TfNSW authentication failed ({response.status})"
                            )
                        if response.status == 429:
                            retry_after_raw = response.headers.get("Retry-After")
                            retry_after = None
                            if retry_after_raw and retry_after_raw.isdigit():
                                retry_after = int(retry_after_raw)
                            raise TfnswRateLimitError(retry_after=retry_after or 60)

                        if response.status in _RETRYABLE_STATUS:
                            body = await response.text()
                            raise TfnswApiError(
                                f"TfNSW temporary error {response.status}: {body[:200]}",
                                status=response.status,
                            )

                        if response.status >= 400:
                            body = await response.text()
                            raise TfnswApiError(
                                f"TfNSW API error {response.status}: {body[:200]}",
                                status=response.status,
                            )

                        if expect_json:
                            return await response.json(content_type=None)
                        return await response.read()

            except TfnswAuthError:
                raise
            except TfnswRateLimitError:
                raise
            except (TimeoutError, aiohttp.ClientConnectionError, TfnswApiError) as err:
                last_error = err
                if isinstance(err, TfnswApiError) and err.status not in _RETRYABLE_STATUS:
                    raise
                if attempt >= _MAX_RETRIES:
                    break
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                _LOGGER.warning(
                    "TfNSW request failed (attempt %s/%s): %s; retrying in %.0fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    err,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        if isinstance(last_error, TfnswApiError):
            raise last_error
        raise TfnswApiError(f"TfNSW request failed after retries: {last_error}") from last_error

    async def async_get_vehicle_positions(self) -> bytes:
        """Fetch GTFS-Realtime vehicle positions protobuf."""
        data = await self._request(
            ENDPOINT_VEHICLE_POS,
            timeout=15.0,
            expect_json=False,
        )
        assert isinstance(data, (bytes, bytearray))
        return bytes(data)

    async def async_get_static_gtfs(self) -> bytes:
        """Download the buses static GTFS ZIP."""
        data = await self._request(
            ENDPOINT_STATIC_GTFS,
            timeout=120.0,
            expect_json=False,
        )
        assert isinstance(data, (bytes, bytearray))
        return bytes(data)

    async def async_get_departures(
        self,
        stop_id: str,
        *,
        when: Any | None = None,
    ) -> dict[str, Any]:
        """Fetch departure board JSON for a stop."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = when or datetime.now(ZoneInfo("Australia/Sydney"))
        params = {
            "outputFormat": "rapidJSON",
            "coordOutputFormat": "EPSG:4326",
            "mode": "direct",
            "type_dm": "stop",
            "name_dm": stop_id,
            "depArrMacro": "dep",
            "itdDate": now.strftime("%Y%m%d"),
            "itdTime": now.strftime("%H%M"),
            "TfNSWDM": "true",
            "version": "10.2.1.42",
        }
        data = await self._request(
            ENDPOINT_DEPARTURE_MON,
            params=params,
            timeout=10.0,
            expect_json=True,
        )
        assert isinstance(data, dict)
        return data

    async def async_validate_api_key(self) -> None:
        """Validate the API key with a lightweight stop_finder call."""
        params = {
            "outputFormat": "rapidJSON",
            "type_sf": "any",
            "name_sf": "Macleay",
            "TfNSWSF": "true",
            "version": "10.2.1.42",
        }
        await self._request(
            ENDPOINT_STOP_FINDER,
            params=params,
            timeout=10.0,
            expect_json=True,
        )

    def describe_request(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Return a redacted URL description for diagnostics."""
        query = f"?{urlencode(params)}" if params else ""
        return f"{self._url(path)}{query}"
