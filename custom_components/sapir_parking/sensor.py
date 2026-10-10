"""Sensors for Sapir Parking."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, NOT_RESERVED_STATE, RESERVED_STATE
from .coordinator import (
    TODAY,
    TOMORROW,
    SapirParkingConfigEntry,
    SapirParkingCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SapirParkingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the parking sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        SapirParkingSensor(coordinator, key) for key in (TODAY, TOMORROW)
    )


class SapirParkingSensor(CoordinatorEntity[SapirParkingCoordinator], SensorEntity):
    """Whether a parking spot is reserved on a given day."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [RESERVED_STATE, NOT_RESERVED_STATE]

    def __init__(self, coordinator: SapirParkingCoordinator, key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = f"parking_{key}"
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=NAME,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str:
        """Return reserved / not_reserved."""
        status = self.coordinator.data[self._key]
        return RESERVED_STATE if status.reserved else NOT_RESERVED_STATE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the reserved spot, or how many spots are free."""
        status = self.coordinator.data[self._key]
        if status.reserved and status.parking_info:
            return dataclasses.asdict(status.parking_info)
        return {"available_count": len(status.all_available_spots)}
