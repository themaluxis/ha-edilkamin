"""Tests for commands: optimistic state and delayed, debounced refresh."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import HomeAssistantError
import httpx
import pytest

from custom_components.edilkamin.api.edilkamin_async_api import NotInRightStateError
from custom_components.edilkamin.climate import EdilkaminClimateEntity
from custom_components.edilkamin.const import CHECK_DELAY, OPTIMISTIC_TIMEOUT
from custom_components.edilkamin.coordinator import EdilkaminCoordinator
from custom_components.edilkamin.fan import PRESET_MODE_AUTO, EdilkaminFan
from custom_components.edilkamin.switch import (
    EdilkaminAirekareSwitch,
    EdilkaminStandByModeSwitch,
)

MAC = "AA:BB:CC:DD:EE:FF"
NOW = 1_760_000_000.0


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    fake = FakeClock()
    with (
        patch("custom_components.edilkamin.entity.time", fake),
        patch("custom_components.edilkamin.coordinator.time", fake),
    ):
        yield fake


class FakeStove:
    """Coordinator stand-in whose blocks were published at given times."""

    def __init__(self, clock: FakeClock) -> None:
        self.published = {"status": clock.now - 5, "nvm": clock.now - 5}
        self.target_temperature = 20
        self.power = True
        self.airkare = False


def make_coordinator(stove: FakeStove):
    coordinator = Mock()
    coordinator.get_mac_address = Mock(return_value=MAC)
    coordinator.async_refresh_after_command = AsyncMock()
    coordinator.get_status_timestamp = Mock(side_effect=lambda b: stove.published[b])
    coordinator.get_temperature = Mock(return_value=19.5)
    coordinator.get_target_temperature = Mock(
        side_effect=lambda: stove.target_temperature
    )
    coordinator.get_fan_speed = Mock(return_value=3)
    coordinator.get_power_status = Mock(side_effect=lambda: stove.power)
    coordinator.is_auto = Mock(return_value=True)
    coordinator.get_manual_power = Mock(return_value=None)
    coordinator.get_airkare_status = Mock(side_effect=lambda: stove.airkare)
    coordinator.get_standby_mode = Mock(return_value=False)
    coordinator.get_standby_waiting_time = Mock(return_value=120)
    return coordinator


@pytest.fixture
def stove(clock):
    return FakeStove(clock)


@pytest.fixture
def coordinator(stove):
    return make_coordinator(stove)


@pytest.fixture
def api():
    api = Mock()
    for name in (
        "set_temperature",
        "set_fan_speed",
        "enable_power",
        "disable_power",
        "enable_auto_mode",
        "disable_auto_mode",
        "set_manual_power_level",
        "enable_airkare",
        "disable_airkare",
        "enable_standby_mode",
        "disable_standby_mode",
    ):
        setattr(api, name, AsyncMock())
    return api


def make_entity(cls, *args):
    entity = cls(*args)
    entity.async_write_ha_state = Mock()
    entity._update_from_coordinator()
    return entity


@pytest.mark.asyncio
async def test_target_temperature_never_goes_back(clock, stove, coordinator, api):
    """20 -> 21 shows 21 at once and keeps it until the stove publishes it."""
    climate = make_entity(EdilkaminClimateEntity, api, coordinator)
    assert climate.target_temperature == 20

    await climate.async_set_temperature(temperature=21)

    api.set_temperature.assert_awaited_once_with(21)
    assert climate.target_temperature == 21
    climate.async_write_ha_state.assert_called()
    coordinator.async_refresh_after_command.assert_awaited_once()

    # Poll with status refreshed but nvm still older than the command
    clock.advance(5)
    stove.published["status"] = clock.now
    climate._handle_coordinator_update()
    assert climate.target_temperature == 21

    # nvm published after the command: cloud value takes over
    clock.advance(5)
    stove.published["nvm"] = clock.now
    stove.target_temperature = 21
    climate._handle_coordinator_update()
    assert climate.target_temperature == 21
    assert climate._optimistic_values == {}


@pytest.mark.asyncio
async def test_optimistic_value_expires_after_timeout(clock, stove, coordinator, api):
    climate = make_entity(EdilkaminClimateEntity, api, coordinator)
    await climate.async_set_temperature(temperature=21)

    clock.advance(OPTIMISTIC_TIMEOUT - 1)
    climate._handle_coordinator_update()
    assert climate.target_temperature == 21

    clock.advance(2)
    climate._handle_coordinator_update()
    assert climate.target_temperature == stove.target_temperature == 20


@pytest.mark.asyncio
async def test_rejected_command_changes_nothing(coordinator, api):
    climate = make_entity(EdilkaminClimateEntity, api, coordinator)
    climate.async_write_ha_state.reset_mock()
    request = httpx.Request("PUT", "https://example.invalid/mqtt/command")
    api.set_temperature.side_effect = httpx.HTTPStatusError(
        "bad request", request=request, response=httpx.Response(400, request=request)
    )

    with pytest.raises(HomeAssistantError, match="rejected the command"):
        await climate.async_set_temperature(temperature=21)

    assert climate.target_temperature == 20
    assert climate._optimistic_values == {}
    climate.async_write_ha_state.assert_not_called()
    coordinator.async_refresh_after_command.assert_not_called()


@pytest.mark.asyncio
async def test_hvac_mode_uses_status_block(clock, stove, coordinator, api):
    climate = make_entity(EdilkaminClimateEntity, api, coordinator)
    assert climate.hvac_mode == HVACMode.HEAT

    await climate.async_set_hvac_mode(HVACMode.OFF)
    api.disable_power.assert_awaited_once()
    assert climate.hvac_mode == HVACMode.OFF

    # Older poll keeps the optimistic value
    climate._handle_coordinator_update()
    assert climate.hvac_mode == HVACMode.OFF

    clock.advance(10)
    stove.published["status"] = clock.now
    stove.power = False
    climate._handle_coordinator_update()
    assert climate.hvac_mode == HVACMode.OFF
    assert climate._optimistic_values == {}


@pytest.mark.asyncio
async def test_preset_and_fan_mode(coordinator, api):
    climate = make_entity(EdilkaminClimateEntity, api, coordinator)

    await climate.async_set_preset_mode("Manual P3")
    api.disable_auto_mode.assert_awaited_once()
    api.set_manual_power_level.assert_awaited_once_with(3)
    assert climate.preset_mode == "Manual P3"

    await climate.async_set_fan_mode("Auto")
    api.set_fan_speed.assert_awaited_once_with(6)
    assert climate.fan_mode == "Auto"

    climate._handle_coordinator_update()
    assert climate.preset_mode == "Manual P3"
    assert climate.fan_mode == "Auto"


@pytest.mark.asyncio
async def test_switch_optimistic(clock, stove, coordinator, api):
    switch = make_entity(EdilkaminAirekareSwitch, api, coordinator)
    assert switch.is_on is False

    await switch.async_turn_on()
    assert switch.is_on is True
    switch._handle_coordinator_update()
    assert switch.is_on is True

    clock.advance(10)
    stove.published["status"] = clock.now
    stove.airkare = True
    switch._handle_coordinator_update()
    assert switch.is_on is True


@pytest.mark.asyncio
async def test_standby_not_in_auto_raises_readable_error(coordinator, api):
    switch = make_entity(EdilkaminStandByModeSwitch, api, coordinator)
    api.enable_standby_mode.side_effect = NotInRightStateError()

    with pytest.raises(HomeAssistantError, match="only available from auto mode"):
        await switch.async_turn_on()

    assert switch.is_on is False


@pytest.mark.asyncio
async def test_fan_speed_and_preset(coordinator, api):
    fan = make_entity(EdilkaminFan, api, 1, coordinator)
    assert fan.is_on is True
    assert fan.percentage == 60

    await fan.async_set_percentage(100)
    api.set_fan_speed.assert_awaited_once_with(5, 1)
    assert fan.percentage == 100
    fan._handle_coordinator_update()
    assert fan.percentage == 100

    await fan.async_set_preset_mode(PRESET_MODE_AUTO)
    api.set_fan_speed.assert_awaited_with(6, 1)
    assert fan.preset_mode == PRESET_MODE_AUTO
    assert fan.percentage is None


class TestRefreshAfterCommand:
    """async_refresh_after_command sends a check and debounces the refresh."""

    @pytest.fixture
    def mock_mqtt_command(self):
        with patch(
            "custom_components.edilkamin.coordinator.edilkamin.mqtt_command",
            new_callable=AsyncMock,
        ) as mock:
            yield mock

    @pytest.fixture
    def real_coordinator(self, clock):  # noqa: ARG002
        coord = EdilkaminCoordinator(Mock(), "user", "pass", MAC)
        coord.refresh_token = AsyncMock(return_value="t.jwt")
        return coord

    @pytest.mark.asyncio
    async def test_three_quick_commands_one_check_one_refresh(
        self, clock, real_coordinator, mock_mqtt_command
    ):
        unsubs = [Mock(), Mock(), Mock()]
        with patch(
            "custom_components.edilkamin.coordinator.async_call_later",
            side_effect=unsubs,
        ) as mock_call_later:
            for _ in range(3):
                await real_coordinator.async_refresh_after_command()
                clock.advance(2)

        mock_mqtt_command.assert_awaited_once_with("t.jwt", MAC, {"name": "check"})
        assert all(call.args[1] == CHECK_DELAY for call in mock_call_later.mock_calls)
        # The first two timers were cancelled: a single refresh stays planned
        unsubs[0].assert_called_once()
        unsubs[1].assert_called_once()
        unsubs[2].assert_not_called()
        assert real_coordinator._unsub_command_refresh is unsubs[2]

    @pytest.mark.asyncio
    async def test_check_respects_cooldown(
        self, clock, real_coordinator, mock_mqtt_command
    ):
        with patch("custom_components.edilkamin.coordinator.async_call_later"):
            real_coordinator._last_check_sent = clock.monotonic()
            await real_coordinator.async_refresh_after_command()
            mock_mqtt_command.assert_not_called()

            clock.advance(61)
            await real_coordinator.async_refresh_after_command()
            mock_mqtt_command.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delayed_refresh_and_shutdown(
        self, real_coordinator, mock_mqtt_command
    ):
        unsub = Mock()
        with patch(
            "custom_components.edilkamin.coordinator.async_call_later",
            return_value=unsub,
        ) as mock_call_later:
            await real_coordinator.async_refresh_after_command()

        mock_mqtt_command.assert_awaited_once()
        job = mock_call_later.call_args.args[2]
        real_coordinator.async_refresh = AsyncMock()
        await job.target(None)
        real_coordinator.async_refresh.assert_awaited_once()
        assert real_coordinator._unsub_command_refresh is None

        with patch(
            "custom_components.edilkamin.coordinator.async_call_later",
            return_value=unsub,
        ):
            await real_coordinator.async_refresh_after_command()
        await real_coordinator.async_shutdown()
        unsub.assert_called_once()
        assert real_coordinator._unsub_command_refresh is None
