"""Sapir Parking API Client."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

TIMEOUT = 20
FLARESOLVERR_TIMEOUT_MS = 60000

_LOGGER: logging.Logger = logging.getLogger(__package__)

DATE_FORMAT = "%Y-%m-%d"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
BASE_URL = "https://sapirparking.com/employee"
LOGIN_URL = f"{BASE_URL}/login"
ADD_SCHEDULE_URL = f"{BASE_URL}/schedule/add"
REMOVE_SCHEDULE_URL = f"{BASE_URL}/schedule/delete"

SESSION_COOKIE_NAME = "session"
CHALLENGE_STATUSES = (403, 429, 503)
CHALLENGE_MARKERS = ("Just a moment...", "challenge-platform", "cf-chl-")


class SapirParkingError(Exception):
    """Base error for the Sapir Parking client."""


class SapirParkingConnectionError(SapirParkingError):
    """The site (or FlareSolverr) could not be reached."""


class SapirParkingAuthError(SapirParkingError):
    """The credentials or session cookie are invalid or expired."""


class SapirParkingParseError(SapirParkingError):
    """The response could not be parsed."""


class CloudflareChallengeError(SapirParkingError):
    """Cloudflare blocked the request and no FlareSolverr is configured."""


@dataclasses.dataclass
class ParkingSpot:
    """Base parking spot interface."""

    floor: int
    spot: int
    date: str


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
    """Parking status for a single date."""

    reserved: bool
    parking_info: ReservedParkingSpot | None
    available_spots: dict[int, list[AvailableParkingSpot]]

    @property
    def all_available_spots(self) -> list[AvailableParkingSpot]:
        """Return every available spot, across all floors."""
        return [spot for spots in self.available_spots.values() for spot in spots]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        return {
            "reserved": self.reserved,
            "parking_info": (
                dataclasses.asdict(self.parking_info) if self.parking_info else None
            ),
            "available_spots": available_spots_as_dict(self.available_spots),
        }


def available_spots_as_dict(
    spots: dict[int, list[AvailableParkingSpot]],
) -> dict[str, list[dict[str, Any]]]:
    """Return available spots as a JSON-safe dict keyed by floor."""
    return {
        str(floor): [dataclasses.asdict(spot) for spot in floor_spots]
        for floor, floor_spots in spots.items()
    }


def is_cloudflare_challenge(status: int, headers: Any, text: str) -> bool:
    """Return True if a response is a Cloudflare challenge page."""
    if status not in CHALLENGE_STATUSES:
        return False
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return any(marker in text for marker in CHALLENGE_MARKERS)


class SapirParkingApiClient:
    """Sapir parking API Client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        session_cookie: str | None = None,
        phone: str | None = None,
        license_number: str | None = None,
        flaresolverr_url: str | None = None,
    ) -> None:
        """Initiate Sapir parking API Client."""
        self._session = session
        self._phone = phone
        self._license_number = license_number
        self._flaresolverr_url = flaresolverr_url.rstrip("/") if flaresolverr_url else None
        self._user_agent = DEFAULT_USER_AGENT
        self._cookies: dict[str, str] = {}
        if session_cookie:
            self._cookies[SESSION_COOKIE_NAME] = session_cookie

    @property
    def session_cookie(self) -> str | None:
        """Return the current session cookie."""
        return self._cookies.get(SESSION_COOKIE_NAME)

    @property
    def _can_login(self) -> bool:
        return bool(self._phone and self._license_number)

    async def async_login(self) -> None:
        """Log in with phone and license number, storing the session cookie."""
        if not self._can_login:
            raise SapirParkingAuthError("No phone/license configured")
        self._cookies.pop(SESSION_COOKIE_NAME, None)
        form = {"Phone": self._phone, "License": self._license_number}
        _, text = await self._request("post", LOGIN_URL, data=form, relogin=False)
        try:
            result = json.loads(text)
        except ValueError:
            result = None
        if isinstance(result, dict) and result.get("Success", 1) != 1:
            raise SapirParkingAuthError(result.get("Message") or "Login rejected")
        if not self.session_cookie:
            raise SapirParkingAuthError("Login did not return a session cookie")

    async def async_check_flaresolverr(self) -> None:
        """Raise SapirParkingConnectionError if FlareSolverr isn't reachable."""
        if not self._flaresolverr_url:
            return
        try:
            async with self._session.get(
                f"{self._flaresolverr_url}/",
                timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            ) as response:
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SapirParkingConnectionError(
                f"FlareSolverr at {self._flaresolverr_url} is not reachable: {err}"
            ) from err
        if "flaresolverr" not in str(data.get("msg", "")).lower():
            raise SapirParkingConnectionError(
                f"{self._flaresolverr_url} does not look like a FlareSolverr instance"
            )

    async def async_get_parking_status(self, date: dt.date) -> ParkingSpotStatus:
        """Get parking status for a date."""
        _, text = await self._request(
            "get", BASE_URL, params={"date": date.strftime(DATE_FORMAT)}
        )
        parser = SapirParkingResponseParser(text)
        return ParkingSpotStatus(
            parser.reserved,
            parser.get_reserved_spot(),
            parser.get_available_spots(),
        )

    async def async_get_available_spots(
        self, date: dt.date
    ) -> dict[int, list[AvailableParkingSpot]]:
        """Get available parking spots for a date."""
        return (await self.async_get_parking_status(date)).available_spots

    async def async_reserve_spot(self, date: dt.date, parking_id: int) -> dict:
        """Reserve a parking spot."""
        date_str = date.strftime(DATE_FORMAT)
        return await self._post_json(
            ADD_SCHEDULE_URL,
            {"ParkingID": str(parking_id), "Date": date_str},
            params={"date": date_str},
        )

    async def async_release_spot(self, date: dt.date, schedule_id: int) -> dict:
        """Release a reserved parking spot."""
        return await self._post_json(
            REMOVE_SCHEDULE_URL,
            {"ScheduleID": str(schedule_id), "Date": date.strftime(DATE_FORMAT)},
        )

    async def _post_json(
        self, url: str, data: dict[str, str], params: dict | None = None
    ) -> dict:
        _, text = await self._request("post", url, data=data, params=params)
        try:
            result = json.loads(text)
        except ValueError as err:
            raise SapirParkingParseError(f"Unexpected response from {url}") from err
        if not isinstance(result, dict) or result.get("Success") != 1:
            message = result.get("Message") if isinstance(result, dict) else None
            raise SapirParkingError(message or f"Request to {url} failed: {result}")
        return result

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        relogin: bool = True,
        solve_challenge: bool = True,
    ) -> tuple[int, str]:
        """Make a request, handling Cloudflare challenges and expired sessions."""
        if (
            relogin
            and self._can_login
            and not self.session_cookie
        ):
            await self.async_login()

        headers = {"User-Agent": self._user_agent}
        if self._cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            ) as response:
                text = await response.text()
                status = response.status
                final_url = response.url
                response_headers = response.headers
                for resp in (*response.history, response):
                    if (cookie := resp.cookies.get(SESSION_COOKIE_NAME)) and cookie.value:
                        self._cookies[SESSION_COOKIE_NAME] = cookie.value
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SapirParkingConnectionError(f"Error fetching {url}: {err}") from err

        if is_cloudflare_challenge(status, response_headers, text):
            if not self._flaresolverr_url:
                raise CloudflareChallengeError(
                    "Blocked by a Cloudflare challenge; configure FlareSolverr"
                )
            if not solve_challenge:
                raise CloudflareChallengeError(
                    "Still blocked by Cloudflare after solving the challenge"
                )
            await self._solve_challenge(url if method == "get" else BASE_URL)
            return await self._request(
                method,
                url,
                params=params,
                data=data,
                relogin=relogin,
                solve_challenge=False,
            )

        if url != LOGIN_URL and (
            final_url.path.rstrip("/").endswith("/login") or is_login_page(text)
        ):
            if relogin and self._can_login:
                _LOGGER.debug("Session expired, logging in again")
                await self.async_login()
                return await self._request(
                    method,
                    url,
                    params=params,
                    data=data,
                    relogin=False,
                    solve_challenge=solve_challenge,
                )
            raise SapirParkingAuthError("Session is invalid or expired")

        if status >= 400:
            raise SapirParkingConnectionError(f"{url} returned HTTP {status}")

        return status, text

    async def _solve_challenge(self, url: str) -> None:
        """Solve a Cloudflare challenge with FlareSolverr and keep its cookies."""
        _LOGGER.debug("Solving Cloudflare challenge for %s using FlareSolverr", url)
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": FLARESOLVERR_TIMEOUT_MS,
        }
        try:
            async with self._session.post(
                f"{self._flaresolverr_url}/v1",
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=FLARESOLVERR_TIMEOUT_MS / 1000 + TIMEOUT
                ),
            ) as response:
                result = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SapirParkingConnectionError(
                f"FlareSolverr at {self._flaresolverr_url} failed: {err}"
            ) from err

        if result.get("status") != "ok":
            raise CloudflareChallengeError(
                f"FlareSolverr could not solve the challenge: {result.get('message')}"
            )
        solution = result.get("solution", {})
        if user_agent := solution.get("userAgent"):
            self._user_agent = user_agent
        for cookie in solution.get("cookies", []):
            # Keep Cloudflare cookies only; our own session cookie stays as is.
            if cookie.get("name") and cookie["name"] != SESSION_COOKIE_NAME:
                self._cookies[cookie["name"]] = cookie["value"]


def is_login_page(text: str) -> bool:
    """Return True if the html is the login page."""
    return 'name="Phone"' in text and 'name="License"' in text


class SapirParkingResponseParser:
    """An helper class to parse html results from SapirParking client."""

    def __init__(self, response: str) -> None:
        """Initialize a SapirParkingResponseParser instance."""
        if is_login_page(response):
            raise SapirParkingAuthError("Session is invalid or expired")
        self.soup = BeautifulSoup(response, "html.parser")
        self.reserved = bool(self._booked_element)

    @property
    def _booked_element(self):
        return self.soup.find("div", {"class": "company-parking-booked"})

    def get_reserved_spot(self) -> ReservedParkingSpot | None:
        """Parse html results to get the reserved parking spot."""
        content = self._booked_element
        if not content:
            return None
        try:
            floor, spot = content.find("div", {"class": "item-title"}).find_all(
                "div", {"class": "chip"}
            )
            data = content.find("button", {"class": "schedule-delete"})
            return ReservedParkingSpot(
                schedule_id=int(data["data-schedule-id"]),
                floor=int(floor.text),
                spot=int(spot.text),
                date=data["data-date"],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            raise SapirParkingParseError("Could not parse reserved spot") from err

    def get_available_spots(self) -> dict[int, list[AvailableParkingSpot]]:
        """Parse html results to get the available parking spots, by floor."""
        content_element = self.soup.find("div", {"class": "list"})
        if content_element is None:
            if self.reserved:
                return {}
            raise SapirParkingParseError("Parking list not found in page")
        spots: dict[int, list[AvailableParkingSpot]] = {}
        try:
            for floor in content_element.find_all("li", {"class": "accordion-item"}):
                floor_id = int(
                    floor.find("div", {"class": "item-title"}).find("span").text
                )
                floor_spots = [
                    AvailableParkingSpot(
                        parking_id=int(spot["data-parking-id"]),
                        floor=floor_id,
                        spot=int(spot.text.strip()),
                        date=spot["data-date"],
                    )
                    for spot in floor.find_all("div", {"class": "parking-button"})
                ]
                if floor_spots:
                    spots[floor_id] = floor_spots
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            raise SapirParkingParseError("Could not parse available spots") from err
        return spots
