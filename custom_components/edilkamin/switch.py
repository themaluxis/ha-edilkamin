"""Platform for sensor integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity

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
    async_api = config_entry.runtime_data.api
    coordinator = config_entry.runtime_data.coordinator

    async_add_devices(
        [
            EdilkaminAirekareSwitch(async_api, coordinator),
            EdilkaminRelaxSwitch(async_api, coordinator),
            EdilkaminChronoModeSwitch(async_api, coordinator),
            EdilkaminStandByModeSwitch(async_api, coordinator),
        ]
    )


class EdilkaminAirekareSwitch(EdilkaminEntity, SwitchEntity):
    """Representation of a Sensor."""

    def __init__(self, api: EdilkaminAsyncApi, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._api = api
        self._attr_icon = "mdi:air-filter"
        self._attr_name = "Airekare"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_airekare_switch"

    def _update_from_coordinator(self) -> None:
        self._attr_is_on = self.coordinator.get_airkare_status()

    async def async_turn_on(self, **_kwargs) -> None:
        """Turn the entity on."""
        await self._async_send_command(self._api.enable_airkare(), _attr_is_on=True)

    async def async_turn_off(self, **_kwargs):
        """Turn the entity off."""
        await self._async_send_command(self._api.disable_airkare(), _attr_is_on=False)


class EdilkaminRelaxSwitch(EdilkaminEntity, SwitchEntity):
    """Representation of a Sensor."""

    def __init__(self, api: EdilkaminAsyncApi, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._api = api
        self._attr_icon = "mdi:weather-night"

        self._attr_name = "Relax mode"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_relax_switch"

    def _update_from_coordinator(self) -> None:
        self._attr_is_on = self.coordinator.get_relax_status()

    async def async_turn_on(self, **_kwargs) -> None:
        """Turn the entity on."""
        await self._async_send_command(self._api.enable_relax(), _attr_is_on=True)

    async def async_turn_off(self, **_kwargs):
        """Turn the entity off."""
        await self._async_send_command(self._api.disable_relax(), _attr_is_on=False)


class EdilkaminChronoModeSwitch(EdilkaminEntity, SwitchEntity):
    """Representation of a Sensor."""

    def __init__(self, api: EdilkaminAsyncApi, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._api = api
        self._attr_icon = "mdi:calendar-clock"

        self._attr_name = "Chrono mode"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_chrono_mode_switch"

    def _update_from_coordinator(self) -> None:
        self._attr_is_on = self.coordinator.get_chrono_mode_status()

    async def async_turn_on(self, **_kwargs) -> None:
        """Turn the entity on."""
        await self._async_send_command(
            self._api.enable_chrono_mode(), block="nvm", _attr_is_on=True
        )

    async def async_turn_off(self, **_kwargs):
        """Turn the entity off."""
        await self._async_send_command(
            self._api.disable_chrono_mode(), block="nvm", _attr_is_on=False
        )


class EdilkaminStandByModeSwitch(EdilkaminEntity, SwitchEntity):
    """Representation of a Sensor."""

    def __init__(self, api: EdilkaminAsyncApi, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._api = api
        self._attr_icon = "mdi:pause-circle-outline"

        self._attr_name = "Stand by mode"

        # standby_waiting_time --> temps d'attente standby

        standby_waiting_time_second = self.coordinator.get_standby_waiting_time()
        standby_minutes, stand_by_sec = divmod(standby_waiting_time_second, 60)
        standby_waiting_time = f"{standby_minutes}:{stand_by_sec} min"

        additional_att = {
            "description": "When the Stand-by function is active, "
            "in the automatic and crono modes, "
            "the product switches off "
            "once the temperature set-point is reached"
            " and turns on again "
            "when the room temperature drops below the chosen value.",
            "details": standby_waiting_time,
        }
        self._attr_extra_state_attributes = additional_att

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_standby_mode_switch"

    def _update_from_coordinator(self) -> None:
        self._attr_is_on = self.coordinator.get_standby_mode()

    async def async_turn_on(self, **_kwargs) -> None:
        """Turn the entity on."""
        await self._async_send_command(
            self._api.enable_standby_mode(), block="nvm", _attr_is_on=True
        )

    async def async_turn_off(self, **_kwargs):
        """Turn the entity off."""
        await self._async_send_command(
            self._api.disable_standby_mode(), block="nvm", _attr_is_on=False
        )
