"""Data update coordinator for Sapir Parking."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ParkingSpotStatus,
    SapirParkingApiClient,
    SapirParkingAuthError,
    SapirParkingError,
)
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER: logging.Logger = logging.getLogger(__package__)

TODAY = "today"
TOMORROW = "tomorrow"

type SapirParkingConfigEntry = ConfigEntry[SapirParkingCoordinator]


class SapirParkingCoordinator(DataUpdateCoordinator[dict[str, ParkingSpotStatus]]):
    """Fetch today's and tomorrow's parking status."""

    config_entry: SapirParkingConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SapirParkingConfigEntry,
        client: SapirParkingApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, ParkingSpotStatus]:
        today = dt_util.now().date()
        try:
            return {
                TODAY: await self.client.async_get_parking_status(today),
                TOMORROW: await self.client.async_get_parking_status(
                    today + timedelta(days=1)
                ),
            }
        except SapirParkingAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SapirParkingError as err:
            raise UpdateFailed(str(err)) from err
