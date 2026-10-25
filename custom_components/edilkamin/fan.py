"""Platform for fan integration."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .entity import EdilkaminEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from custom_components.edilkamin.api.edilkamin_async_api import EdilkaminAsyncApi

    from .data import EdilkaminConfigEntry

_LOGGER = logging.getLogger(__name__)

SPEED_RANGE = (1, 5)  # away is not included in speeds and instead mapped to off

SPEED_AUTO = 6
PRESET_MODE_AUTO = "Auto"
PRESET_MODES = [PRESET_MODE_AUTO]

async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: EdilkaminConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Add sensors for passed config_entry in HA."""
    async_api = config_entry.runtime_data.api
    coordinator = config_entry.runtime_data.coordinator

    nb_fans = coordinator.get_nb_fans()

    fans = [EdilkaminFan(api=async_api, index=1, coordinator=coordinator)]

    if nb_fans > 1:
        fans.extend(
            EdilkaminFan(api=async_api, index=i, coordinator=coordinator)
            for i in range(2, nb_fans + 1)
        )

    async_add_devices(fans)


class EdilkaminFan(EdilkaminEntity, FanEntity):
    """Representation of a Fan."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    _attr_preset_modes = PRESET_MODES
    _attr_speed_count = int_states_in_range(SPEED_RANGE)

    def __init__(self, api: EdilkaminAsyncApi, index: int, coordinator) -> None:
        """Initialize the fan."""
        super().__init__(coordinator)
        self._api = api
        self._index = index
        self._attr_is_on = False
        self._attr_percentage = None
        self._attr_preset_mode = None

        self._attr_name = f"Fan {index}"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_fan{self._index}"

    @property
    def is_on(self) -> bool:
        """Return true when the stove is on."""
        return self._attr_is_on

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self._async_send_command(
            self._api.set_fan_speed(speed, self._index),
            block="nvm",
            _attr_percentage=percentage,
            _attr_preset_mode=None,
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if preset_mode == PRESET_MODE_AUTO:
            await self._async_send_command(
                self._api.set_fan_speed(SPEED_AUTO, self._index),
                block="nvm",
                _attr_percentage=None,
                _attr_preset_mode=PRESET_MODE_AUTO,
            )

    def _update_from_coordinator(self) -> None:
        """Set the fan attributes from the coordinator data."""
        self._attr_is_on = self.coordinator.get_power_status() is True
        speed = self.coordinator.get_fan_speed(self._index)
        if speed == SPEED_AUTO:
            self._attr_preset_mode = PRESET_MODE_AUTO
            self._attr_percentage = None
        elif isinstance(speed, int) and SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
            self._attr_preset_mode = None
            self._attr_percentage = ranged_value_to_percentage(SPEED_RANGE, speed)
        if not self._attr_is_on:
            self._attr_percentage = None
