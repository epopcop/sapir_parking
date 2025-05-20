""" Sapir Parking Custom Integration"""

import asyncio
import dataclasses
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SapirParkingApiClient
from .const import CONF_SESSION_COOKIE, DOMAIN, PLATFORMS, STARTUP_MESSAGE, DATE_FORMAT

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ParkingSpotNotReservedException(Exception):
    pass


class BadSapirParkingRequest(Exception):
    pass


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.debug(STARTUP_MESSAGE)

    session_cookie = entry.data.get(CONF_SESSION_COOKIE)

    session = async_get_clientsession(hass)
    client = SapirParkingApiClient(session, session_cookie)

    async def handle_get_available_spots(call):
        return await client.async_get_available_spots(get_date(call))

    async def handle_async_get_status(call):
        return dataclasses.asdict(await client.async_get_parking_status(get_date(call)))

    async def handle_async_reserve_spot(call):
        parking_id = call.data.get("parking_id")
        if not parking_id:
            raise BadSapirParkingRequest("Missing parking id")
        return await client.async_reserve_spot(get_date(call), parking_id)

    async def handle_async_release_spot(call):
        spot = await client.async_get_parking_status(get_date(call))
        if not spot.reserved:
            raise ParkingSpotNotReservedException
        return await client.async_release_spot(
            datetime.strptime(spot.parking_info.date, DATE_FORMAT),
            spot.parking_info.schedule_id,
        )

    hass.services.async_register(
        DOMAIN,
        "get_available_spots",
        handle_get_available_spots,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_status",
        handle_async_get_status,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "release_parking_spot",
        handle_async_release_spot,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "reserve_parking_spot",
        handle_async_reserve_spot,
        supports_response=SupportsResponse.ONLY,
    )
    return True


def get_date(call):
    """Get datetime from call."""
    date = call.data.get("Date", datetime.today())
    if isinstance(date, str):
        date = datetime.strptime(date, DATE_FORMAT)
    return date
