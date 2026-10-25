"""Platform for sensor integration."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime

from .entity import EdilkaminEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import EdilkaminConfigEntry

_LOGGER = logging.getLogger(__name__)

OPERATIONAL_STATES = {
    0: "Off",
    1: "Ignition",
    2: "On",
    3: "Shutdown",
    4: "Cooling",
    5: "Alarm",
    6: "Final cleaning",
    7: "Unknown",
}


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: EdilkaminConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    """Add sensors for passed config_entry in HA."""

    coordinator = config_entry.runtime_data.coordinator

    sensors = [
        EdilkaminTemperatureSensor(coordinator),
        EdilkaminFanSensor(coordinator, 1),
        EdilkaminAlarmSensor(coordinator),
        EdilkaminActualPowerSensor(coordinator),
        EdilkaminOperationalSensor(coordinator),
        EdilkaminAutonomySensor(coordinator),
        EdilkaminPowerOnsSensor(coordinator),
        EdilkaminDataAgeSensor(coordinator),
        EdilkaminLastUpdateSensor(coordinator),
    ]

    # "puffer" is the Edilkamin API key for the buffer tank water temperature.
    temperatures = coordinator.get_temperatures()
    for key, name in (
        ("puffer", "Buffer temperature"),
        ("boiler", "Boiler temperature"),
    ):
        if key in temperatures:
            sensors.append(EdilkaminWaterTemperatureSensor(coordinator, key, name))

    nb_fans = coordinator.get_nb_fans()

    if nb_fans > 1:
        sensors.extend(
            EdilkaminFanSensor(coordinator, i) for i in range(2, nb_fans + 1)
        )

    async_add_devices(sensors)


class EdilkaminTemperatureSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None

        self._attr_name = "Temperature"
        self._attr_icon = "mdi:thermometer"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return UnitOfTemperature.CELSIUS

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_temperature"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        temperature = self.coordinator.get_temperature()
        if temperature is not None and temperature != 0:
            self._state = temperature

        self.async_write_ha_state()


class EdilkaminFanSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, index: int) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._attr_icon = "mdi:fan"
        self._index = index

        self._attr_name = f"Fan {index}"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.POWER

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_fan{self._index}_sensor"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.get_fan_speed(self._index)
        self.async_write_ha_state()


class EdilkaminAlarmSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._attr_icon = "mdi:alert"
        self._attributes: dict[str, Any] = {}

        self._attr_name = "Nb alarms"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.POWER

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_nb_alarms_sensor"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return attributes for the sensor."""
        return self._attributes

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.get_nb_alarms()
        alarms = self.coordinator.get_alarms()

        errors = {
            "errors": [],
        }

        for alarm in alarms:
            data = {
                "type": alarm["type"],
                "timestamp": time.strftime(
                    "%d-%m-%Y %H:%M:%S", time.localtime(alarm["timestamp"])
                ),
            }
            errors["errors"].append(data)

        self._attributes = errors
        self.async_write_ha_state()


class EdilkaminActualPowerSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None

        self._attr_name = "Actual power"
        self._attr_icon = "mdi:flash"

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.POWER

    @property
    def native_unit_of_measurement(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return None

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_actual_power"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.get_actual_power()
        self.async_write_ha_state()


class EdilkaminOperationalSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None
        self._attr_icon = "mdi:eye"
        self._attributes: dict[str, Any] = {}

        self._attr_name = "Operational phase"
        self._attr_options = list(OPERATIONAL_STATES.values())

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.ENUM

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_operational_phase_sensor"

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        op_state = self.coordinator.get_operational_phase()

        if op_state in OPERATIONAL_STATES:
            self._attr_native_value = OPERATIONAL_STATES[op_state]
        else:
            # Error operational code unknown, shows only the code
            self._attr_native_value = OPERATIONAL_STATES[7]

        additional_att = {"value": op_state}
        self._attr_extra_state_attributes = additional_att
        self.async_write_ha_state()


class EdilkaminAutonomySensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None

        self._attr_name = "Autonomy"
        self._attr_icon = "mdi:timer"

        additional_att = {
            "description": "Time remaining before the stove turns off"
            " if no pellets are added"
        }
        self._attr_extra_state_attributes = additional_att

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return SensorDeviceClass.DURATION

    @property
    def native_unit_of_measurement(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return "min"

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_autonomy"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        autonomy_second = self.coordinator.get_autonomy_second()
        if autonomy_second is None:
            return
        # Convert seconds to minutes
        minutes = divmod(autonomy_second, 60)
        self._state = f"{minutes}"
        self.async_write_ha_state()


class EdilkaminPowerOnsSensor(EdilkaminEntity, SensorEntity):
    """Representation of a Sensor."""

    def __init__(self, coordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._state = None

        self._attr_name = "Power ons"
        self._attr_icon = "mdi:counter"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self._mac_address}_power_ons"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.get_power_ons()
        self.async_write_ha_state()


class EdilkaminWaterTemperatureSensor(EdilkaminEntity, SensorEntity):
    """A hydronic temperature from the existing cloud coordinator."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._temperature_key = key
        self._attr_name = name
        self._attr_unique_id = f"{self._mac_address}_{key}_temperature"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.get_water_temperature(self._temperature_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class EdilkaminDataAgeSensor(EdilkaminEntity, SensorEntity):
    """Age of the data published by the stove (now - status.timestamp)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Data age"
        self._attr_unique_id = f"{self._mac_address}_data_age"

    @property
    def available(self) -> bool:
        """Stay available to show how old the data is."""
        return True

    @property
    def native_value(self) -> int | None:
        age = self.coordinator.get_data_age()
        return None if age is None else round(age)


class EdilkaminLastUpdateSensor(EdilkaminEntity, SensorEntity):
    """Time the stove last published its status (status.timestamp)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:update"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Last stove update"
        self._attr_unique_id = f"{self._mac_address}_last_stove_update"

    @property
    def available(self) -> bool:
        """Stay available to show when the stove last published."""
        return True

    @property
    def native_value(self) -> datetime | None:
        timestamp = self.coordinator.get_status_timestamp()
        return None if timestamp is None else datetime.fromtimestamp(timestamp, UTC)
