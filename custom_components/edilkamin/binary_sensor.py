"""Platform for sensor integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import EdilkaminEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from custom_components.edilkamin.api.edilkamin_async_api import (
        EdilkaminAsyncApi,
    )

    from .data import EdilkaminConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: EdilkaminConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Add sensors for passed config_entry in HA."""
    coordinator = config_entry.runtime_data.coordinator
    async_api = config_entry.runtime_data.api

    async_add_devices(
        [
            EdilkaminTankBinarySensor(coordinator),
            EdilkaminCheckBinarySensor(async_api),
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


class EdilkaminCheckBinarySensor(BinarySensorEntity):
    """Representation of a Sensor."""

    _attr_has_entity_name = True

    def __init__(self, api: EdilkaminAsyncApi) -> None:
        """Initialize the sensor."""
        self._state = None
        self._api = api
        self._mac_address = self._api.get_mac_address()

        self._attr_name = "Check configuration"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._mac_address)})
        self._attr_icon = "mdi:check-circle"

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
        return f"{self._mac_address}_check_binary_sensor"

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            await self._api.check()
            self._state = False
            self.async_write_ha_state()
        except Exception:
            self._state = True
            self.async_write_ha_state()
            _LOGGER.exception("Exception occurred during check configuration")
