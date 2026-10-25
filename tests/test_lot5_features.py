"""Tests for hvac_action, the status sensors and the target temperature range."""

import asyncio
from unittest.mock import AsyncMock, Mock

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
import pytest

from custom_components.edilkamin.climate import (
    EdilkaminClimateEntity,
    compute_hvac_action,
)
from custom_components.edilkamin.const import (
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
)
from custom_components.edilkamin.coordinator import EdilkaminCoordinator
from custom_components.edilkamin.sensor import (
    STATUS_SENSORS,
    EdilkaminFanSensor,
    EdilkaminPowerOnsSensor,
    EdilkaminStatusSensor,
    async_setup_entry,
)

MAC = "AA:BB:CC:DD:EE:FF"

DEVICE_INFO = {
    "status": {
        "timestamp": 1_760_000_000_000,
        "commands": {"power": True},
        "state": {
            "operational_phase": 2,
            "sub_operational_phase": 0,
            "stove_state": 6,
            "actual_power": 3,
            "alarm_type": 0,
        },
        "temperatures": {
            "enviroment": 20.5,
            "thermocouple": 145,
            "board": 38,
            "feeler_ntc_1": 21,
        },
        "counters": {"service_time": 1234},
    },
    "nvm": {"timestamp": 1_759_999_000_000, "user_parameters": {}},
}


@pytest.fixture
def coordinator():
    coord = EdilkaminCoordinator(Mock(), "user", "pass", MAC)
    coord._device_info = DEVICE_INFO
    return coord


@pytest.mark.parametrize(
    ("power", "phase", "expected"),
    [
        # Cases observed on the reference stove (specification table)
        (True, 2, HVACAction.HEATING),  # heating at P3, stove_state 6
        (True, 0, HVACAction.IDLE),  # automatic standby, stove_state 2
        (False, None, HVACAction.OFF),  # turned off by the user
        (False, 3, HVACAction.OFF),
        # Other phases
        (True, 1, HVACAction.PREHEATING),
        (True, 3, HVACAction.IDLE),
        (True, 4, HVACAction.IDLE),
        (True, 6, HVACAction.IDLE),
        (True, 5, None),  # alarm
        (True, 42, None),  # unknown phase
        (True, None, None),
        (None, 2, None),  # no data yet
    ],
)
def test_hvac_action_mapping(power, phase, expected):
    assert compute_hvac_action(power, phase) == expected


def test_unknown_phase_logs_debug(caplog):
    with caplog.at_level("DEBUG", logger="custom_components.edilkamin.climate"):
        assert compute_hvac_action(power=True, operational_phase=42) is None
    assert "operational phase 42" in caplog.text


def test_climate_exposes_hvac_action_and_range(coordinator):
    climate = EdilkaminClimateEntity(Mock(), coordinator)
    climate._update_from_coordinator()

    assert climate.hvac_mode == HVACMode.HEAT
    assert climate.hvac_action == HVACAction.HEATING
    assert climate.min_temp == MIN_TARGET_TEMPERATURE
    assert climate.max_temp == MAX_TARGET_TEMPERATURE
    assert climate.target_temperature_step == 0.5


@pytest.mark.asyncio
async def test_turning_off_shows_off_action(coordinator):
    api = Mock()
    api.disable_power = AsyncMock()
    coordinator.async_refresh_after_command = AsyncMock()
    climate = EdilkaminClimateEntity(api, coordinator)
    climate.async_write_ha_state = Mock()
    climate._update_from_coordinator()

    await climate.async_set_hvac_mode(HVACMode.OFF)

    assert climate.hvac_action == HVACAction.OFF


def test_status_sensors_values_and_categories(coordinator):
    sensors = {
        d.key: EdilkaminStatusSensor(coordinator, d) for d in STATUS_SENSORS
    }

    smoke = sensors["smoke_temperature"]
    assert smoke.native_value == 145
    assert smoke.device_class == SensorDeviceClass.TEMPERATURE
    assert smoke.native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert smoke.entity_category is None
    assert smoke.unique_id == f"{MAC}_smoke_temperature"

    assert sensors["alarm_code"].native_value == 0
    assert sensors["board_temperature"].native_value == 38
    assert sensors["ntc_1_temperature"].native_value == 21
    assert sensors["hours_before_service"].native_value == 1234
    assert sensors["hours_before_service"].native_unit_of_measurement == (
        UnitOfTime.HOURS
    )
    assert sensors["operational_phase_code"].native_value == 2
    assert sensors["sub_operational_phase"].native_value == 0

    diagnostics = {
        key
        for key, sensor in sensors.items()
        if sensor.entity_category == EntityCategory.DIAGNOSTIC
    }
    assert diagnostics == set(sensors) - {"smoke_temperature"}
    disabled = {
        key
        for key, sensor in sensors.items()
        if not sensor.entity_registry_enabled_default
    }
    assert disabled == {
        "ntc_1_temperature",
        "operational_phase_code",
        "sub_operational_phase",
    }


def test_setup_creates_only_reported_status_sensors(coordinator):
    coordinator._device_info = {
        "status": {"temperatures": {"thermocouple": 145}, "state": {}},
        "nvm": {},
    }
    entry = Mock()
    entry.runtime_data.coordinator = coordinator
    add_entities = Mock()

    asyncio.run(async_setup_entry(Mock(), entry, add_entities))

    keys = {
        sensor.entity_description.key
        for sensor in add_entities.call_args.args[0]
        if isinstance(sensor, EdilkaminStatusSensor)
    }
    assert keys == {"smoke_temperature"}


@pytest.mark.parametrize("sensor_cls", [EdilkaminPowerOnsSensor, EdilkaminFanSensor])
def test_nvm_sensors_expose_nvm_timestamp(coordinator, sensor_cls):
    sensor = (
        sensor_cls(coordinator, 1)
        if sensor_cls is EdilkaminFanSensor
        else sensor_cls(coordinator)
    )
    sensor.async_write_ha_state = Mock()

    sensor._handle_coordinator_update()

    assert sensor.extra_state_attributes == {
        "nvm_timestamp": "2025-10-09T08:36:40+00:00"
    }


def test_get_status_value(coordinator):
    assert coordinator.get_status_value("state", "alarm_type") == 0
    assert coordinator.get_status_value("state", "missing") is None
    assert coordinator.get_status_value("commands", "power", "deeper") is None
    coordinator._device_info = {}
    assert coordinator.get_status_value("state", "alarm_type") is None
