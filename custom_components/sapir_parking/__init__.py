"""Sapir Parking Custom Integration."""

from __future__ import annotations

import dataclasses
import datetime as dt
import random

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import (
    AvailableParkingSpot,
    ParkingSpotStatus,
    SapirParkingApiClient,
    SapirParkingError,
    available_spots_as_dict,
)
from .const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_LOGIN,
    CONF_AUTH_METHOD,
    CONF_FLARESOLVERR_URL,
    CONF_LICENSE,
    CONF_PHONE,
    CONF_SESSION_COOKIE,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SapirParkingConfigEntry, SapirParkingCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_DATE = "date"
ATTR_PARKING_ID = "parking_id"
ATTR_PREFERRED_SPOTS = "preferred_spots"

DATE_SCHEMA = vol.Schema({vol.Optional(ATTR_DATE): cv.date})
RESERVE_SCHEMA = DATE_SCHEMA.extend(
    {
        vol.Optional(ATTR_PARKING_ID): vol.Coerce(int),
        vol.Optional(ATTR_PREFERRED_SPOTS): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("floor"): vol.Coerce(int),
                        vol.Required("spot"): vol.Coerce(int),
                    }
                )
            ],
        ),
    }
)


def create_client(
    hass: HomeAssistant, data: dict, flaresolverr_url: str | None
) -> SapirParkingApiClient:
    """Create an API client from config entry data."""
    # Cookies are managed by the client itself, so keep them out of the jar.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    if data.get(CONF_AUTH_METHOD, AUTH_METHOD_COOKIE) == AUTH_METHOD_LOGIN:
        return SapirParkingApiClient(
            session,
            phone=data[CONF_PHONE],
            license_number=data[CONF_LICENSE],
            flaresolverr_url=flaresolverr_url,
        )
    return SapirParkingApiClient(
        session,
        session_cookie=data[CONF_SESSION_COOKIE],
        flaresolverr_url=flaresolverr_url,
    )


def get_flaresolverr_url(entry: SapirParkingConfigEntry) -> str | None:
    """Return the FlareSolverr URL, with options taking precedence over data."""
    if CONF_FLARESOLVERR_URL in entry.options:
        return entry.options[CONF_FLARESOLVERR_URL] or None
    return entry.data.get(CONF_FLARESOLVERR_URL) or None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""

    hass.services.async_register(
        DOMAIN,
        "get_available_spots",
        _handle_get_available_spots,
        schema=DATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_status",
        _handle_get_status,
        schema=DATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "reserve_parking_spot",
        _handle_reserve_spot,
        schema=RESERVE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "release_parking_spot",
        _handle_release_spot,
        schema=DATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SapirParkingConfigEntry) -> bool:
    """Set up this integration using UI."""
    client = create_client(hass, dict(entry.data), get_flaresolverr_url(entry))
    coordinator = SapirParkingCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async def _midnight_refresh(now: dt.datetime) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_time_change(hass, _midnight_refresh, hour=0, minute=1, second=0)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SapirParkingConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: SapirParkingConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _get_coordinator(hass: HomeAssistant) -> SapirParkingCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


def _get_date(call: ServiceCall) -> dt.date:
    return call.data.get(ATTR_DATE) or dt_util.now().date()


async def _get_status(
    coordinator: SapirParkingCoordinator, date: dt.date
) -> ParkingSpotStatus:
    try:
        return await coordinator.client.async_get_parking_status(date)
    except SapirParkingError as err:
        raise HomeAssistantError(str(err)) from err


async def _handle_get_available_spots(call: ServiceCall) -> ServiceResponse:
    coordinator = _get_coordinator(call.hass)
    status = await _get_status(coordinator, _get_date(call))
    return available_spots_as_dict(status.available_spots)


async def _handle_get_status(call: ServiceCall) -> ServiceResponse:
    coordinator = _get_coordinator(call.hass)
    status = await _get_status(coordinator, _get_date(call))
    return status.as_dict()


async def _handle_reserve_spot(call: ServiceCall) -> ServiceResponse:
    coordinator = _get_coordinator(call.hass)
    date = _get_date(call)
    status = await _get_status(coordinator, date)
    if status.reserved:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="already_reserved",
            translation_placeholders={"date": date.isoformat()},
        )

    spot = _choose_spot(
        status,
        call.data.get(ATTR_PARKING_ID),
        call.data.get(ATTR_PREFERRED_SPOTS, []),
    )
    try:
        result = await coordinator.client.async_reserve_spot(date, spot.parking_id)
    except SapirParkingError as err:
        raise HomeAssistantError(f"Failed to reserve spot: {err}") from err
    await coordinator.async_request_refresh()
    return {**result, **dataclasses.asdict(spot)}


async def _handle_release_spot(call: ServiceCall) -> ServiceResponse:
    coordinator = _get_coordinator(call.hass)
    date = _get_date(call)
    status = await _get_status(coordinator, date)
    if not status.reserved or not status.parking_info:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_reserved",
            translation_placeholders={"date": date.isoformat()},
        )
    try:
        result = await coordinator.client.async_release_spot(
            date, status.parking_info.schedule_id
        )
    except SapirParkingError as err:
        raise HomeAssistantError(f"Failed to release spot: {err}") from err
    await coordinator.async_request_refresh()
    return result


def _choose_spot(
    status: ParkingSpotStatus,
    parking_id: int | None,
    preferred_spots: list[dict[str, int]],
) -> AvailableParkingSpot:
    """Pick a spot: by id, else the first free preferred spot, else at random."""
    available = status.all_available_spots
    if parking_id is not None:
        for spot in available:
            if spot.parking_id == parking_id:
                return spot
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="spot_not_found",
            translation_placeholders={"parking_id": str(parking_id)},
        )

    for preferred in preferred_spots:
        for spot in available:
            if spot.floor == preferred["floor"] and spot.spot == preferred["spot"]:
                return spot

    if not available:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_spots_available"
        )
    return random.choice(available)
