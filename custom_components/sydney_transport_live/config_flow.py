"""Config flow for Sydney Transport Live."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import TfnswApiClient, normalize_api_key
from .api.static_gtfs import GtfsStaticStore
from .const import (
    CONF_API_KEY,
    CONF_DEPARTURE_INTERVAL,
    CONF_DIRECTION_ID,
    CONF_DIRECTION_LABEL,
    CONF_POSITION_INTERVAL,
    CONF_ROUTE_SHORT_NAME,
    CONF_STOP_CODE,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CURATED_STOPS,
    DEFAULT_DEPARTURE_INTERVAL,
    DEFAULT_DIRECTION_LABEL,
    DEFAULT_POSITION_INTERVAL,
    DEFAULT_ROUTE_SHORT_NAME,
    DEFAULT_STOP_NAME,
    DOMAIN,
    MIN_DEPARTURE_INTERVAL_SECONDS,
    MIN_POSITION_INTERVAL_SECONDS,
)
from .exceptions import TfnswAuthError, TfnswError
from .helpers.filtering import normalize_route_short_name

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


async def _validate_api_key(hass: HomeAssistant, api_key: str) -> None:
    session = async_get_clientsession(hass)
    client = TfnswApiClient(session=session, api_key=api_key)
    await client.async_validate_api_key()


class SydneyTransportLiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sydney Transport Live."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._route_short_name: str = DEFAULT_ROUTE_SHORT_NAME
        self._store: GtfsStaticStore | None = None
        self._directions: list[tuple[int, str]] = []
        self._preferred_direction_id: int = 0
        self._curated_stops: list[Any] = []
        self._stop_id: str = ""
        self._stop_name: str = DEFAULT_STOP_NAME
        self._stop_code: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect and validate the TfNSW API key."""
        errors: dict[str, str] = {}
        description_placeholders = {"error_detail": ""}

        if user_input is not None:
            api_key = normalize_api_key(user_input[CONF_API_KEY])
            if not api_key:
                errors["base"] = "invalid_auth"
            else:
                try:
                    await _validate_api_key(self.hass, api_key)
                except TfnswAuthError as err:
                    _LOGGER.warning("TfNSW API key rejected during config flow: %s", err)
                    errors["base"] = "invalid_auth"
                    description_placeholders["error_detail"] = str(err)
                except TfnswError as err:
                    _LOGGER.warning("TfNSW connect error during config flow: %s", err)
                    errors["base"] = "cannot_connect"
                    description_placeholders["error_detail"] = str(err)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.exception("Unexpected error validating TfNSW API key")
                    errors["base"] = "unknown"
                    description_placeholders["error_detail"] = str(err)
                else:
                    self._api_key = api_key
                    if self._reauth_entry:
                        return await self._async_finish_reauth()
                    return await self.async_step_route()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_route(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select route short name (default 311).

        Static GTFS is intentionally NOT downloaded here — the buses schedule
        ZIP is large and was causing cannot_connect during setup on HA Green.
        Curated defaults are used; GTFS is fetched later during entry setup.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._route_short_name = normalize_route_short_name(
                user_input[CONF_ROUTE_SHORT_NAME]
            )
            if not self._route_short_name:
                errors["base"] = "route_not_found"
            else:
                # Seed curated Potts Point stops without needing the schedule ZIP.
                from .models import StopInfo

                self._store = None
                self._curated_stops = [
                    StopInfo(
                        stop_id=seed["stop_code"],
                        stop_name=seed["name"],
                        stop_code=seed["stop_code"],
                    )
                    for seed in CURATED_STOPS
                ]
                self._directions = [
                    (0, DEFAULT_DIRECTION_LABEL),
                    (1, "Opposite direction"),
                ]
                self._preferred_direction_id = 0
                return await self.async_step_stop()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ROUTE_SHORT_NAME, default=DEFAULT_ROUTE_SHORT_NAME
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="route",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select stop — curated Potts Point list plus custom stop id."""
        errors: dict[str, str] = {}
        stop_options: dict[str, str] = {}
        default_stop_key = None

        for stop in self._curated_stops:
            key = stop.stop_id
            label = stop.stop_name
            if stop.stop_code:
                label = f"{label} ({stop.stop_code})"
            stop_options[key] = label
            if DEFAULT_STOP_NAME.lower() in stop.stop_name.lower() and "opp" not in stop.stop_name.lower():
                default_stop_key = key

        if not default_stop_key and stop_options:
            default_stop_key = next(iter(stop_options))

        stop_options["__custom__"] = "Enter a custom stop ID…"

        if user_input is not None:
            selected = user_input["stop_choice"]
            if selected == "__custom__":
                return await self.async_step_custom_stop()

            stop = None
            if self._store:
                stop = self._store.get_stop(selected)
            if stop is None:
                for candidate in self._curated_stops:
                    if candidate.stop_id == selected:
                        stop = candidate
                        break
            if stop is None:
                errors["base"] = "invalid_stop"
            else:
                self._stop_id = stop.stop_id
                self._stop_name = stop.stop_name
                self._stop_code = stop.stop_code
                return await self.async_step_direction()

        schema = vol.Schema(
            {
                vol.Required(
                    "stop_choice",
                    default=default_stop_key or "__custom__",
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=k, label=v)
                            for k, v in stop_options.items()
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="stop",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_custom_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual stop id / code entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            stop_ref = user_input[CONF_STOP_ID].strip()
            stop_name = user_input.get(CONF_STOP_NAME, stop_ref).strip()
            stop = None
            if self._store:
                stop = self._store.get_stop(stop_ref) or self._store.find_stop_by_code(
                    stop_ref
                )
            if stop is not None:
                self._stop_id = stop.stop_id
                self._stop_name = stop.stop_name
                self._stop_code = stop.stop_code
            else:
                self._stop_id = stop_ref
                self._stop_name = stop_name or stop_ref
                self._stop_code = stop_ref
            return await self.async_step_direction()

        schema = vol.Schema(
            {
                vol.Required(CONF_STOP_ID): selector.TextSelector(),
                vol.Optional(CONF_STOP_NAME, default=DEFAULT_STOP_NAME): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="custom_stop",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_direction(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select travel direction."""
        options = [
            selector.SelectOptionDict(value=str(did), label=label)
            for did, label in self._directions
        ]
        if not options:
            options = [
                selector.SelectOptionDict(
                    value="0", label=DEFAULT_DIRECTION_LABEL
                )
            ]

        default = str(self._preferred_direction_id)

        if user_input is not None:
            direction_id = int(user_input[CONF_DIRECTION_ID])
            label = next(
                (lbl for did, lbl in self._directions if did == direction_id),
                DEFAULT_DIRECTION_LABEL,
            )
            await self.async_set_unique_id(
                f"{self._route_short_name}_{self._stop_id}_{direction_id}"
            )
            self._abort_if_unique_id_configured()

            title = f"{self._route_short_name} · {self._stop_name} → {label}"
            return self.async_create_entry(
                title=title,
                data={CONF_API_KEY: self._api_key},
                options={
                    CONF_ROUTE_SHORT_NAME: self._route_short_name,
                    CONF_STOP_ID: self._stop_id,
                    CONF_STOP_NAME: self._stop_name,
                    CONF_STOP_CODE: self._stop_code,
                    CONF_DIRECTION_ID: direction_id,
                    CONF_DIRECTION_LABEL: label,
                    CONF_POSITION_INTERVAL: int(
                        DEFAULT_POSITION_INTERVAL.total_seconds()
                    ),
                    CONF_DEPARTURE_INTERVAL: int(
                        DEFAULT_DEPARTURE_INTERVAL.total_seconds()
                    ),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DIRECTION_ID, default=default
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="direction", data_schema=schema)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Re-authenticate when the API key is rejected."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    async def _async_finish_reauth(self) -> FlowResult:
        assert self._reauth_entry is not None
        assert self._api_key is not None
        self.hass.config_entries.async_update_entry(
            self._reauth_entry,
            data={**self._reauth_entry.data, CONF_API_KEY: self._api_key},
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return SydneyTransportLiveOptionsFlow()


class SydneyTransportLiveOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage route/stop/interval options."""
        current = self.config_entry.options
        errors: dict[str, str] = {}

        if user_input is not None:
            pos = int(user_input[CONF_POSITION_INTERVAL])
            dep = int(user_input[CONF_DEPARTURE_INTERVAL])
            if pos < MIN_POSITION_INTERVAL_SECONDS:
                errors[CONF_POSITION_INTERVAL] = "interval_too_low"
            if dep < MIN_DEPARTURE_INTERVAL_SECONDS:
                errors[CONF_DEPARTURE_INTERVAL] = "interval_too_low"
            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_ROUTE_SHORT_NAME: normalize_route_short_name(
                            user_input[CONF_ROUTE_SHORT_NAME]
                        ),
                        CONF_STOP_ID: user_input[CONF_STOP_ID].strip(),
                        CONF_STOP_NAME: user_input[CONF_STOP_NAME].strip(),
                        CONF_STOP_CODE: user_input.get(CONF_STOP_CODE) or current.get(CONF_STOP_CODE),
                        CONF_DIRECTION_ID: int(user_input[CONF_DIRECTION_ID]),
                        CONF_DIRECTION_LABEL: user_input[CONF_DIRECTION_LABEL].strip(),
                        CONF_POSITION_INTERVAL: pos,
                        CONF_DEPARTURE_INTERVAL: dep,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ROUTE_SHORT_NAME,
                    default=current.get(CONF_ROUTE_SHORT_NAME, DEFAULT_ROUTE_SHORT_NAME),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_STOP_ID,
                    default=current.get(CONF_STOP_ID, ""),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_STOP_NAME,
                    default=current.get(CONF_STOP_NAME, DEFAULT_STOP_NAME),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_DIRECTION_ID,
                    default=current.get(CONF_DIRECTION_ID, 0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_DIRECTION_LABEL,
                    default=current.get(CONF_DIRECTION_LABEL, DEFAULT_DIRECTION_LABEL),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_POSITION_INTERVAL,
                    default=current.get(
                        CONF_POSITION_INTERVAL,
                        int(DEFAULT_POSITION_INTERVAL.total_seconds()),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_POSITION_INTERVAL_SECONDS,
                        max=120,
                        unit_of_measurement="seconds",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_DEPARTURE_INTERVAL,
                    default=current.get(
                        CONF_DEPARTURE_INTERVAL,
                        int(DEFAULT_DEPARTURE_INTERVAL.total_seconds()),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_DEPARTURE_INTERVAL_SECONDS,
                        max=300,
                        unit_of_measurement="seconds",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
