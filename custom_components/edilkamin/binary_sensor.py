"""Platform for sensor integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Add sensors for passed config_entry in HA."""
    coordinator = hass.data[DOMAIN]["coordinator"]

    async_add_devices(
        [
            EdilkaminTankBinarySensor(coordinator),
            EdilkaminCheckBinarySensor(coordinator),
        ]
    )


class EdilkaminTankBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._mac_address = self.coordinator.get_mac_address()
        self._attr_icon = "mdi:storage-tank"

        self._attr_name = "Tank"
        self._attr_device_info = {"identifiers": {("edilkamin", self._mac_address)}}

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


class EdilkaminCheckBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that reports a problem when the coordinator update fails."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._mac_address = self.coordinator.get_mac_address()

        self._attr_name = "Check configuration"
        self._attr_device_info = {"identifiers": {("edilkamin", self._mac_address)}}
        self._attr_icon = "mdi:check-circle"

    @property
    def is_on(self):
        """Return True if the binary sensor is on (problem detected)."""
        return self._state

    @property
    def device_class(self):
        """Return the class of the binary sensor."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_check_binary_sensor"

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # If the coordinator last update was successful, no problem
        self._state = self.coordinator.last_update_success is False
        self.async_write_ha_state()
