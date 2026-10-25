"""Tests for the data freshness logic of the coordinator (check on stale data)."""

from datetime import timedelta
import logging
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from custom_components.edilkamin.binary_sensor import (
    EdilkaminCheckBinarySensor,
    EdilkaminTankBinarySensor,
)
from custom_components.edilkamin.const import (
    CHECK_COOLDOWN,
    CHECK_DELAY,
    STALE_AFTER,
    UNAVAILABLE_AFTER,
    UPDATE_TIMEOUT,
)
from custom_components.edilkamin.coordinator import EdilkaminCoordinator
from custom_components.edilkamin.sensor import (
    EdilkaminDataAgeSensor,
    EdilkaminLastUpdateSensor,
    EdilkaminTemperatureSensor,
)

MODULE = "custom_components.edilkamin.coordinator"
MAC = "AA:BB:CC:DD:EE:FF"
NOW = 1_760_000_000.0


class FakeClock:
    """Controls time.time() and time.monotonic() as seen by the coordinator."""

    def __init__(self) -> None:
        self.now = NOW

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def payload(age: float, clock: FakeClock) -> dict:
    """Build a device/info payload whose status is `age` seconds old."""
    return {"status": {"timestamp": int((clock.now - age) * 1000)}, "nvm": {}}


@pytest.fixture
def clock():
    fake = FakeClock()
    with patch(f"{MODULE}.time", fake):
        yield fake


@pytest.fixture
def coordinator(clock):  # noqa: ARG001
    hass = Mock()
    hass.async_add_executor_job = AsyncMock()
    coord = EdilkaminCoordinator(hass, "user", "pass", MAC)
    coord._check_delay = 0
    with patch.object(coord, "refresh_token", AsyncMock(return_value="t.jwt")):
        yield coord


@pytest.fixture
def mock_device_info():
    with patch(f"{MODULE}.edilkamin.device_info", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_mqtt_command():
    with patch(f"{MODULE}.edilkamin.mqtt_command", new_callable=AsyncMock) as mock:
        mock.return_value = "Command executed successfully"
        yield mock


def test_defaults():
    """Defaults match the specification and the official app."""
    coord = EdilkaminCoordinator(Mock(), "user", "pass", MAC)
    assert coord.update_interval == timedelta(seconds=15)
    assert coord._stale_after == STALE_AFTER == 90
    assert coord._check_delay == CHECK_DELAY == 12
    assert coord._check_cooldown == CHECK_COOLDOWN == 60
    assert coord._unavailable_after == UNAVAILABLE_AFTER == 300
    assert UPDATE_TIMEOUT == 30


@pytest.mark.asyncio
async def test_fresh_data_sends_no_check(
    coordinator, clock, mock_device_info, mock_mqtt_command
):
    mock_device_info.return_value = payload(10, clock)

    data = await coordinator._async_update_data()

    assert data == mock_device_info.return_value
    mock_device_info.assert_awaited_once_with("t.jwt", MAC)
    mock_mqtt_command.assert_not_called()
    assert coordinator.get_data_age() == pytest.approx(10, abs=0.01)


@pytest.mark.asyncio
async def test_stale_data_sends_check_then_reads_again(
    coordinator, clock, mock_device_info, mock_mqtt_command
):
    stale, fresh = payload(200, clock), payload(1, clock)
    mock_device_info.side_effect = [stale, fresh]

    data = await coordinator._async_update_data()

    assert data is fresh
    assert mock_device_info.await_count == 2
    mock_mqtt_command.assert_awaited_once_with("t.jwt", MAC, {"name": "check"})
    assert coordinator.last_check_success is True


@pytest.mark.asyncio
async def test_still_stale_after_check_logs_warning_and_keeps_data(
    coordinator, clock, mock_device_info, mock_mqtt_command, caplog
):
    first, second = payload(200, clock), payload(195, clock)
    mock_device_info.side_effect = [first, second]

    with caplog.at_level(logging.WARNING, logger=MODULE):
        data = await coordinator._async_update_data()

    assert data is second
    assert coordinator._device_info is second
    mock_mqtt_command.assert_awaited_once()
    assert "still 195 s old" in caplog.text


@pytest.mark.asyncio
async def test_cooldown_limits_checks_to_one_per_minute(
    coordinator, clock, mock_device_info, mock_mqtt_command
):
    mock_device_info.side_effect = lambda *_: payload(200, clock)

    await coordinator._async_update_data()
    clock.advance(15)
    await coordinator._async_update_data()
    clock.advance(15)
    await coordinator._async_update_data()

    assert mock_mqtt_command.await_count == 1
    # 2 reads for the cycle with a check, 1 read for each cycle in cooldown
    assert mock_device_info.await_count == 4

    clock.advance(CHECK_COOLDOWN)
    await coordinator._async_update_data()
    assert mock_mqtt_command.await_count == 2


@pytest.mark.asyncio
async def test_failed_check_keeps_data_without_rereading(
    coordinator, clock, mock_device_info, mock_mqtt_command
):
    stale = payload(200, clock)
    mock_device_info.return_value = stale
    mock_mqtt_command.side_effect = httpx.ConnectError("boom")

    data = await coordinator._async_update_data()

    assert data is stale
    mock_device_info.assert_awaited_once()
    assert coordinator.last_check_success is False


@pytest.mark.asyncio
async def test_missing_timestamp_sends_no_check(
    coordinator, mock_device_info, mock_mqtt_command
):
    mock_device_info.return_value = {"status": {}}

    await coordinator._async_update_data()

    mock_mqtt_command.assert_not_called()
    assert coordinator.get_data_age() is None
    assert coordinator.is_data_too_old() is False


def test_entities_unavailable_when_cloud_is_frozen(coordinator, clock):
    """Past 300 s, entities are unavailable but the diagnostics stay available."""
    coordinator._device_info = payload(UNAVAILABLE_AFTER - 1, clock)
    tank = EdilkaminTankBinarySensor(coordinator)
    temperature = EdilkaminTemperatureSensor(coordinator)
    age = EdilkaminDataAgeSensor(coordinator)
    last_update = EdilkaminLastUpdateSensor(coordinator)
    check = EdilkaminCheckBinarySensor(coordinator)

    assert tank.available
    assert temperature.available

    clock.advance(2)

    assert coordinator.is_data_too_old()
    assert not tank.available
    assert not temperature.available
    assert age.available
    assert age.native_value == UNAVAILABLE_AFTER + 1
    assert last_update.available
    assert last_update.native_value.timestamp() == pytest.approx(
        NOW - UNAVAILABLE_AFTER + 1, abs=1
    )
    assert check.available


def test_check_sensor_reflects_coordinator(coordinator):
    """The check binary sensor never polls and mirrors the coordinator."""
    check = EdilkaminCheckBinarySensor(coordinator)

    assert check.should_poll is False
    assert check.is_on is False

    coordinator.last_check_success = False
    assert check.is_on is True

    coordinator.last_check_success = True
    coordinator.last_update_success = False
    assert check.is_on is True
