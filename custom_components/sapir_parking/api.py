"""Sapir Parking API Client."""

import dataclasses
import datetime as dt
import logging
import socket

import aiohttp
from bs4 import BeautifulSoup

from .const import DATE_FORMAT

TIMEOUT = 10

_LOGGER: logging.Logger = logging.getLogger(__package__)

HEADERS = {
    "Content-type": "application/json; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
}
BASE_URL = "https://sapirparking.com/employee"
LOGIN_URL = f"{BASE_URL}/login"
ADD_SCHEDULE_URL = f"{BASE_URL}/schedule/add"
REMOVE_SCHEDULE_URL = f"{BASE_URL}/schedule/delete"


@dataclasses.dataclass
class ParkingSpot:
    """Base parking spot interface."""

    floor: int
    spot: int
    date: dt.datetime | str


@dataclasses.dataclass
class AvailableParkingSpot(ParkingSpot):
    """Available parking spot interface."""

    parking_id: int


@dataclasses.dataclass
class ReservedParkingSpot(ParkingSpot):
    """Reserved parking spot interface."""

    schedule_id: int


@dataclasses.dataclass
class ParkingSpotStatus:
    """Parking status."""

    reserved: bool
    parking_info: ReservedParkingSpot
    available_spots: dict[str, list[AvailableParkingSpot]]


class SapirParkingApiClient:
    """Sapir parking API Client."""

    def __init__(
        self, session: aiohttp.ClientSession, session_cookie: str | None = None
    ) -> None:
        """Initiate Spair parking API Client."""
        self._session = session
        self._session_headers = {}
        if session_cookie:
            self._session_headers = {"Cookie": f"session={session_cookie}"}

    async def async_login(self, phone: str, license: str) -> dict:
        """Login to Sapir parking API."""
        form = aiohttp.FormData()
        form.add_fields(("Phone", phone), ("License", license))
        res = await self.api_wrapper("post", LOGIN_URL, data=form)
        if res.status >= 200 and res.status < 300:
            self._session_headers = {
                "Cookie": f"session={res.cookies.get('session').value}"
            }
        return await res.json()

    async def async_get_parking_status(self, date: dt.datetime) -> ParkingSpotStatus:
        """Get parking status."""
        params = {"date": date.strftime(DATE_FORMAT)}
        res = SapirParkingResponseParser(
            await self.api_wrapper("get", BASE_URL, params=params)
        )
        return ParkingSpotStatus(
            res.reserved,
            res.get_reserved_spot(),
            res.get_available_spots(),
        )

    async def async_get_available_spots(self, date: dt.datetime) -> dict:
        """Get available parking spots."""
        params = {"date": date.strftime(DATE_FORMAT)}
        spots = await self.api_wrapper("get", BASE_URL, params=params)
        return SapirParkingResponseParser(spots).get_available_spots()

    async def async_reserve_spot(self, date: dt.datetime, parking_id: int):
        """Reserve a parking spot."""
        form = aiohttp.FormData()
        form.add_fields(("ParkingID", parking_id), ("Date", date.strftime(DATE_FORMAT)))
        res = await self.api_wrapper(
            "post",
            ADD_SCHEDULE_URL,
            data=form,
            params={"date": date.strftime(DATE_FORMAT)},
        )
        return await res.json()

    async def async_release_spot(self, date: dt.datetime, schedule_id: int) -> dict:
        """Release a parking slot."""
        form = aiohttp.FormData()
        form.add_fields(
            ("ScheduleID", schedule_id), ("Date", date.strftime(DATE_FORMAT))
        )
        res = await self.api_wrapper("post", REMOVE_SCHEDULE_URL, data=form)
        return await res.json()

    async def api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Get information from the API."""
        if headers:
            headers = {**headers, **self._session_headers}
        else:
            headers = self._session_headers
        try:
            if method == "get":
                response = await self._session.get(url, headers=headers, params=params)
                return await response.text()

            elif method == "post":  # noqa: RET505
                return await self._session.post(
                    url, headers=headers, data=data, params=params
                )

        except TimeoutError as exception:
            _LOGGER.error(
                "Timeout error fetching information from %s - %s",
                url,
                exception,
            )

        except (KeyError, TypeError) as exception:
            _LOGGER.error(
                "Error parsing information from %s - %s",
                url,
                exception,
            )
        except (aiohttp.ClientError, socket.gaierror) as exception:
            _LOGGER.error(
                "Error fetching information from %s - %s",
                url,
                exception,
            )
        except Exception as exception:  # pylint: disable=broad-except  # noqa: BLE001
            _LOGGER.error("Something really wrong happened! - %s", exception)


class SapirParkingResponseParser:
    """An helper class to parse html results from SapirParking client."""

    def __init__(self, response: str) -> None:
        """Initialize a SapirParkingResponseParser instance."""
        self.soup = BeautifulSoup(response, "html.parser")
        self.reserved = False
        if self.soup.find("div", {"class": "company-parking-booked"}):
            self.reserved = True

    def get_reserved_spot(self):
        """Parse html results to get the reserved parking spot."""
        content = self.soup.find("div", {"class": "company-parking-booked"})
        if content:
            floor, spot = content.find("div", {"item-title"}).find_all(
                "div", {"class": "chip"}
            )
            data = content.find("button", {"class": "schedule-delete"})
            return ReservedParkingSpot(
                schedule_id=int(data["data-schedule-id"]),
                floor=int(floor.text),
                spot=int(spot.text),
                date=data["data-date"],
            )
        return {}

    def get_available_spots(self) -> dict[str, list[AvailableParkingSpot]]:
        """Parse html results to get the available parking spots."""
        content_element = self.soup.find("div", {"class": "list"})
        spots = {}
        for floor in content_element.find_all("li", {"class": "accordion-item"}):
            floor_id = int(floor.find("div", {"class": "item-title"}).find("span").text)
            spots[floor_id] = []
            for spot in floor.find_all("div", {"class": "parking-button"}):
                spot_name = spot.text.strip()
                spot_id = spot["data-parking-id"]
                spot_date = spot["data-date"]
                spots[floor_id].append(
                    AvailableParkingSpot(
                        parking_id=int(spot_id),
                        floor=int(floor_id),
                        spot=int(spot_name),
                        date=spot_date,
                    )
                )
        return spots
