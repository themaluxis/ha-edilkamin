"""Tests for config entry setup, unload and multi-instance isolation."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
import httpx
import pytest

from custom_components.edilkamin import async_setup_entry, async_unload_entry
from custom_components.edilkamin.binary_sensor import (
    EdilkaminCheckBinarySensor,
    EdilkaminTankBinarySensor,
)
from custom_components.edilkamin.climate import EdilkaminClimateEntity
from custom_components.edilkamin.coordinator import EdilkaminCoordinator
from custom_components.edilkamin.fan import EdilkaminFan
from custom_components.edilkamin.sensor import (
    EdilkaminActualPowerSensor,
    EdilkaminAlarmSensor,
    EdilkaminAutonomySensor,
    EdilkaminFanSensor,
    EdilkaminOperationalSensor,
    EdilkaminPowerOnsSensor,
    EdilkaminTemperatureSensor,
    EdilkaminWaterTemperatureSensor,
)
from custom_components.edilkamin.switch import (
    EdilkaminAirekareSwitch,
    EdilkaminChronoModeSwitch,
    EdilkaminRelaxSwitch,
    EdilkaminStandByModeSwitch,
)

MODULE = "custom_components.edilkamin.coordinator"
MAC_1 = "AA:BB:CC:DD:EE:01"
MAC_2 = "AA:BB:CC:DD:EE:02"


def make_hass():
    hass = Mock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.async_add_executor_job = AsyncMock(return_value="token.jwt")
    return hass


def make_entry(mac, entry_id):
    entry = Mock()
    entry.entry_id = entry_id
    entry.data = {"mac_address": mac, "username": "user", "password": "pass"}
    entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    return entry


@pytest.mark.asyncio
@patch.object(EdilkaminCoordinator, "async_config_entry_first_refresh")
async def test_two_entries_are_isolated(mock_first_refresh):
    """Each entry owns its coordinator and API, nothing lands in hass.data."""
    hass = make_hass()
    entry_1 = make_entry(MAC_1, "one")
    entry_2 = make_entry(MAC_2, "two")

    assert await async_setup_entry(hass, entry_1)
    assert await async_setup_entry(hass, entry_2)

    data_1 = entry_1.runtime_data
    data_2 = entry_2.runtime_data
    assert data_1.coordinator is not data_2.coordinator
    assert data_1.coordinator.get_mac_address() == MAC_1
    assert data_2.coordinator.get_mac_address() == MAC_2
    assert data_1.api.get_mac_address() == MAC_1
    assert data_2.api.get_mac_address() == MAC_2
    assert data_1.coordinator.config_entry is entry_1
    assert data_2.coordinator.config_entry is entry_2
    assert hass.data == {}
    assert mock_first_refresh.await_count == 2


@pytest.mark.asyncio
@patch(f"{MODULE}.edilkamin.device_info", new_callable=AsyncMock)
async def test_setup_not_ready_when_cloud_unreachable(mock_device_info):
    """An unreachable cloud at startup raises ConfigEntryNotReady (HA retries)."""
    mock_device_info.side_effect = httpx.ConnectError("unreachable")
    hass = make_hass()
    entry = make_entry(MAC_1, "one")

    with (
        patch.object(EdilkaminCoordinator, "refresh_token", return_value="t.jwt"),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)

    hass.config_entries.async_forward_entry_setups.assert_not_called()


@pytest.mark.asyncio
@patch.object(EdilkaminCoordinator, "async_config_entry_first_refresh")
async def test_unload_shuts_down_coordinator(mock_first_refresh):
    """Unloading the entry stops the coordinator of that entry only."""
    hass = make_hass()
    entry_1 = make_entry(MAC_1, "one")
    entry_2 = make_entry(MAC_2, "two")
    await async_setup_entry(hass, entry_1)
    await async_setup_entry(hass, entry_2)

    with patch.object(
        EdilkaminCoordinator, "async_shutdown", autospec=True
    ) as mock_shutdown:
        assert await async_unload_entry(hass, entry_1)

    assert mock_first_refresh.await_count == 2
    mock_shutdown.assert_awaited_once_with(entry_1.runtime_data.coordinator)


def test_unique_ids_are_preserved():
    """Moving to a common base class must not change any unique_id."""
    coordinator = Mock()
    coordinator.get_mac_address = Mock(return_value=MAC_1)
    coordinator.get_standby_waiting_time = Mock(return_value=120)
    api = Mock()
    api.get_mac_address = Mock(return_value=MAC_1)

    entities = [
        EdilkaminTankBinarySensor(coordinator),
        EdilkaminCheckBinarySensor(coordinator),
        EdilkaminClimateEntity(api, coordinator),
        EdilkaminFan(api=api, index=1, coordinator=coordinator),
        EdilkaminFan(api=api, index=2, coordinator=coordinator),
        EdilkaminTemperatureSensor(coordinator),
        EdilkaminFanSensor(coordinator, 1),
        EdilkaminAlarmSensor(coordinator),
        EdilkaminActualPowerSensor(coordinator),
        EdilkaminOperationalSensor(coordinator),
        EdilkaminAutonomySensor(coordinator),
        EdilkaminPowerOnsSensor(coordinator),
        EdilkaminWaterTemperatureSensor(coordinator, "puffer", "Buffer temperature"),
        EdilkaminAirekareSwitch(api, coordinator),
        EdilkaminRelaxSwitch(api, coordinator),
        EdilkaminChronoModeSwitch(api, coordinator),
        EdilkaminStandByModeSwitch(api, coordinator),
    ]

    assert [entity.unique_id for entity in entities] == [
        f"{MAC_1}_tank_binary_sensor",
        f"{MAC_1}_check_binary_sensor",
        f"{MAC_1}_climate",
        f"{MAC_1}_fan1",
        f"{MAC_1}_fan2",
        f"{MAC_1}_temperature",
        f"{MAC_1}_fan1_sensor",
        f"{MAC_1}_nb_alarms_sensor",
        f"{MAC_1}_actual_power",
        f"{MAC_1}_operational_phase_sensor",
        f"{MAC_1}_autonomy",
        f"{MAC_1}_power_ons",
        f"{MAC_1}_puffer_temperature",
        f"{MAC_1}_airekare_switch",
        f"{MAC_1}_relax_switch",
        f"{MAC_1}_chrono_mode_switch",
        f"{MAC_1}_standby_mode_switch",
    ]
    for entity in entities:
        assert entity.has_entity_name
        assert entity.device_info["identifiers"] == {("edilkamin", MAC_1)}
