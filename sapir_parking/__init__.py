"""Sapir Parking Custom Integration."""

import dataclasses
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SapirParkingApiClient
from .const import CONF_LICENSE, CONF_PHONE, DATE_FORMAT, DOMAIN, STARTUP_MESSAGE

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ParkingSpotNotReservedException(Exception):
    """Exception raised when trying to release a parking spot that is not reserved."""


class BadSapirParkingRequest(Exception):
    """Exception raised when a bad request is made to the Sapir Parking API."""


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.debug(STARTUP_MESSAGE)

    phone_number = entry.data.get(CONF_PHONE)
    license_plate = entry.data.get(CONF_LICENSE)

    session = async_get_clientsession(hass)
    client = SapirParkingApiClient(session)
    try:
        await client.async_login(phone_number, license_plate)
    except Exception as err:
        raise ConfigEntryNotReady from err

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
    date = call.data.get("date", datetime.today())
    if isinstance(date, str):
        date = datetime.strptime(date, DATE_FORMAT)
    return date
