"""Sapir Parking Custom Integration."""

import dataclasses
from datetime import datetime
import logging
import random

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ParkingSpot, SapirParkingApiClient
from .const import (
    DATE_FORMAT,
    DOMAIN,
    NOT_RESERVED_STATE,
    PARKING_ENTITY,
    RESERVED_STATE,
    STARTUP_MESSAGE,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ParkingSpotNotReservedException(Exception):
    """Exception raised when trying to release a parking spot that is not reserved."""


class BadSapirParkingRequest(Exception):
    """Exception raised when a bad request is made to the Sapir Parking API."""


class ParkingSpotAlreadyReservedException(Exception):
    """Exception raised when trying to reserve a parking spot that is already reserved."""


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.debug(STARTUP_MESSAGE)

    session_cookie = entry.data.get("session_cookie")

    session = async_get_clientsession(hass)
    client = SapirParkingApiClient(session, session_cookie)

    async def handle_get_available_spots(call):
        return await client.async_get_available_spots(get_date(call))

    async def handle_async_get_status(call):
        res = await client.async_get_parking_status(get_date(call))
        if res.reserved:
            hass.states.async_set(
                PARKING_ENTITY, RESERVED_STATE, dataclasses.asdict(res.parking_info)
            )
        else:
            hass.states.async_set(PARKING_ENTITY, NOT_RESERVED_STATE)
        return dataclasses.asdict(res)

    async def handle_async_reserve_spot(call):
        parking_id = call.data.get("parking_id", None)
        preferred_spots = call.data.get("preferred_spots", [])
        date = get_date(call)

        spot = None
        if parking_id:
            spot = await get_spot_by_id(client, parking_id, date)

        elif preferred_spots:
            spot = await get_spot_by_preferred_spots(client, preferred_spots, date)

        if not spot:
            spot = await get_random_available_spot(client, date)

        res = await client.async_reserve_spot(date, spot.parking_id)
        if res.get("Success") != 1:
            raise BadSapirParkingRequest("Failed to reserve spot.")
        hass.states.async_set(PARKING_ENTITY, RESERVED_STATE, dataclasses.asdict(spot))
        return {
            **res,
            **dataclasses.asdict(spot),
        }

    async def handle_async_release_spot(call):
        spot = await client.async_get_parking_status(get_date(call))
        if not spot.reserved:
            raise ParkingSpotNotReservedException
        res = await client.async_release_spot(
            datetime.strptime(spot.parking_info.date, DATE_FORMAT),
            spot.parking_info.schedule_id,
        )
        if res.get("Success") != 1:
            raise BadSapirParkingRequest("Failed to release spot.")
        hass.states.async_set(PARKING_ENTITY, NOT_RESERVED_STATE)
        return res

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


async def get_random_available_spot(client, date):
    """Get a random available parking spot."""
    status = await client.async_get_parking_status(date)
    if status.reserved:
        raise ParkingSpotAlreadyReservedException
    if not status.available_spots:
        raise BadSapirParkingRequest("No available parking spots found.")
    _, floor = random.choice(list(status.available_spots.items()))
    return random.choice(floor)


async def get_spot_by_id(client, parking_id, date):
    """Get a parking spot by its ID."""
    status = await client.async_get_parking_status(date)
    if status.reserved:
        raise ParkingSpotAlreadyReservedException
    for spots in status.available_spots.values():
        for spot in spots:
            if spot.parking_id == parking_id:
                return spot
    raise BadSapirParkingRequest(f"Parking ID {parking_id} not found.")


async def get_spot_by_preferred_spots(client, preferred_spots, date):
    """Get a parking spot based on preferred spots."""
    if not isinstance(preferred_spots, list):
        raise BadSapirParkingRequest("Preferred spots must be a list.")
    preferred_spots = [
        ParkingSpot(floor=spot["floor"], spot=spot["spot"], date=date)
        for spot in preferred_spots
    ]
    status = await client.async_get_parking_status(date)
    if status.reserved:
        raise ParkingSpotAlreadyReservedException
    for spot in preferred_spots:
        if spot.floor in status.available_spots:
            if spot := list(
                filter(
                    lambda x: x.spot == spot.spot,
                    status.available_spots[spot.floor],
                )
            ):
                return spot[0]

    return None  # No preferred spot found, will fall back to random spot if needed.
