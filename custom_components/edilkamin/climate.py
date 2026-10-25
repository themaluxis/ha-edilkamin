"""Platform for climate integration.

Inspired by nghaye/ha-edilkamin.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import (
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    TARGET_TEMPERATURE_STEP,
)
from .entity import EdilkaminEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from custom_components.edilkamin.api.edilkamin_async_api import EdilkaminAsyncApi

    from .data import EdilkaminConfigEntry

_LOGGER = logging.getLogger(__name__)

CLIMATE_HVAC_MODE_MANAGED = [HVACMode.HEAT, HVACMode.OFF]


FAN_PRESET_MODE_AUTO = "Auto"

FAN_MODES_MANAGED = ["1", "2", "3", "4", "5", FAN_PRESET_MODE_AUTO]


PRESET_AUTO = "Auto"
PRESET_1 = "Manual P1"
PRESET_2 = "Manual P2"
PRESET_3 = "Manual P3"
PRESET_4 = "Manual P4"
PRESET_5 = "Manual P5"

PRESET_MODES = [PRESET_AUTO, PRESET_1, PRESET_2, PRESET_3, PRESET_4, PRESET_5]
# status.state.operational_phase -> action while the stove is powered on.
# Phases match OPERATIONAL_STATES of sensor.py: 0 off (automatic standby),
# 1 ignition, 2 on, 3 shutdown, 4 cooling, 5 alarm, 6 final cleaning.
# Shutdown, cooling and final cleaning happen while going to standby.
OPERATIONAL_PHASE_TO_HVAC_ACTION = {
    0: HVACAction.IDLE,
    1: HVACAction.PREHEATING,
    2: HVACAction.HEATING,
    3: HVACAction.IDLE,
    4: HVACAction.IDLE,
    6: HVACAction.IDLE,
}


def compute_hvac_action(power, operational_phase) -> HVACAction | None:
    """Return the HVAC action from status.commands.power and the phase."""
    if power is False:
        return HVACAction.OFF
    if power is not True:
        return None
    action = OPERATIONAL_PHASE_TO_HVAC_ACTION.get(operational_phase)
    if action is None:
        _LOGGER.debug("No HVAC action for operational phase %s", operational_phase)
    return action


PRESET_MODE_TO_POWER = {
    "Manual P1": 1,
    "Manual P2": 2,
    "Manual P3": 3,
    "Manual P4": 4,
    "Manual P5": 5,
}


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: EdilkaminConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Add sensors for passed config_entry in HA."""

    async_api = config_entry.runtime_data.api
    coordinator = config_entry.runtime_data.coordinator

    async_add_devices([EdilkaminClimateEntity(async_api, coordinator)])


class EdilkaminClimateEntity(EdilkaminEntity, ClimateEntity):
    """Representation of a Climate."""

    def __init__(self, api: EdilkaminAsyncApi, coordinator) -> None:
        """Initialize the climate."""
        super().__init__(coordinator)
        self.api = api

        self._state = None
        self._attr_current_temperature = None
        self._attr_target_temperature = None

        self._attr_fan_modes = FAN_MODES_MANAGED
        self._attr_fan_mode = "1"  # default fan speed

        self._attr_hvac_modes = CLIMATE_HVAC_MODE_MANAGED
        self._attr_hvac_mode = HVACMode.OFF  # default hvac mode

        self._attr_max_temp = MAX_TARGET_TEMPERATURE
        self._attr_min_temp = MIN_TARGET_TEMPERATURE
        self._attr_target_temperature_step = TARGET_TEMPERATURE_STEP
        self._attr_hvac_action = None

        self._attr_preset_modes = PRESET_MODES
        self._attr_preset_mode = PRESET_AUTO

        # Main feature of the device: the entity takes the device name
        self._attr_name = None

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_climate"

    @property
    def temperature_unit(self):
        """The unit of temperature measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self):
        """Bitmap of supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        speed = 6 if fan_mode == FAN_PRESET_MODE_AUTO else fan_mode  # 6 is auto mode
        await self._async_send_command(
            self.api.set_fan_speed(speed), block="nvm", _attr_fan_mode=fan_mode
        )

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_tmp = kwargs.get(ATTR_TEMPERATURE)
        if target_tmp is None:
            return
        await self._async_send_command(
            self.api.set_temperature(target_tmp),
            block="nvm",
            _attr_target_temperature=target_tmp,
        )

    def _update_from_coordinator(self) -> None:
        """Set the climate attributes from the coordinator data."""
        temperature = self.coordinator.get_temperature()
        if temperature is not None and temperature != 0:
            self._attr_current_temperature = temperature

        self._attr_target_temperature = self.coordinator.get_target_temperature()

        fan_speed = self.coordinator.get_fan_speed()
        if fan_speed == 6:  # auto mode
            self._attr_fan_mode = FAN_PRESET_MODE_AUTO
        elif fan_speed is not None:
            self._attr_fan_mode = str(fan_speed)

        power = self.coordinator.get_power_status()
        if power is True:
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = compute_hvac_action(
            power, self.coordinator.get_operational_phase()
        )

        if self.coordinator.is_auto():
            self._attr_preset_mode = PRESET_AUTO
        else:
            manual_power = self.coordinator.get_manual_power()
            if isinstance(manual_power, int) and 0 < manual_power < len(PRESET_MODES):
                self._attr_preset_mode = PRESET_MODES[manual_power]

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode not in CLIMATE_HVAC_MODE_MANAGED:
            msg = f"Unsupported HVAC mode: {hvac_mode}"
            raise ValueError(msg)

        if hvac_mode == HVACMode.OFF:
            command = self.api.disable_power()
        else:
            command = self.api.enable_power()

        optimistic = {"_attr_hvac_mode": hvac_mode}
        if hvac_mode == HVACMode.OFF:
            optimistic["_attr_hvac_action"] = HVACAction.OFF
        await self._async_send_command(command, **optimistic)

    async def async_turn_on(self):
        """Turn on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode) -> None:
        """Set new target preset mode."""
        await self._async_send_command(
            self._async_apply_preset(preset_mode),
            block="nvm",
            _attr_preset_mode=preset_mode,
        )

    async def _async_apply_preset(self, preset_mode) -> None:
        if preset_mode == PRESET_AUTO:
            await self.api.enable_auto_mode()
        else:
            await self.api.disable_auto_mode()
            await self.api.set_manual_power_level(PRESET_MODE_TO_POWER[preset_mode])
