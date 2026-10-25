"""Platform for sensor integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import EdilkaminEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import EdilkaminConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: EdilkaminConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Add sensors for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_devices(
        [
            EdilkaminTankBinarySensor(coordinator),
            EdilkaminCheckBinarySensor(coordinator),
        ]
    )


class EdilkaminTankBinarySensor(EdilkaminEntity, BinarySensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._attr_icon = "mdi:storage-tank"

        self._attr_name = "Tank"

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self._state

    @property
    def device_class(self):
        """Return the class of the binary sensor."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_tank_binary_sensor"

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.get_status_tank()
        self.async_write_ha_state()


class EdilkaminCheckBinarySensor(EdilkaminEntity, BinarySensorEntity):
    """Problem sensor reflecting the cloud reads and checks of the coordinator.

    It sends nothing by itself: the coordinator decides when a check is needed.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Check configuration"
        self._attr_unique_id = f"{self._mac_address}_check_binary_sensor"

    @property
    def available(self) -> bool:
        """Stay available: this sensor reports the cloud problems."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the last read or the last check failed."""
        return (
            not self.coordinator.last_update_success
            or self.coordinator.last_check_success is False
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return the details of the last check."""
        last_check_time = self.coordinator.last_check_time
        return {
            "last_check": last_check_time.isoformat() if last_check_time else None,
            "last_check_success": self.coordinator.last_check_success,
        }
