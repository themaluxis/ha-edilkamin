"""Tests for re-authentication, invalid credentials and the reauth flow."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
import httpx
import pytest

from custom_components.edilkamin.api.edilkamin_async_api import (
    EdilkaminAsyncApi,
    NotInRightStateError,
    is_invalid_credentials_error,
)
from custom_components.edilkamin.config_flow import ConfigFlow
from custom_components.edilkamin.coordinator import EdilkaminCoordinator
from custom_components.edilkamin.switch import EdilkaminStandByModeSwitch

COORDINATOR = "custom_components.edilkamin.coordinator"
API = "custom_components.edilkamin.api.edilkamin_async_api"
MAC = "AA:BB:CC:DD:EE:FF"


class NotAuthorizedException(Exception):  # noqa: N818
    """Same class name as the error raised by Cognito for a bad password."""


def http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/device/x/info")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


class DummyHass:
    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


@pytest.fixture
def coordinator():
    coord = EdilkaminCoordinator(DummyHass(), "user", "pass", MAC)
    coord._token = "revoked.jwt"  # noqa: S105
    with patch.object(coord, "is_token_expired", return_value=False):
        yield coord


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
@patch(f"{COORDINATOR}.edilkamin.sign_in", return_value="fresh.jwt")
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_revoked_token_signs_in_again_once(
    mock_device_info, mock_sign_in, coordinator, status
):
    """A refused token is dropped, a new one is fetched and the call retried."""
    mock_device_info.side_effect = [http_error(status), {"status": {}}]

    data = await coordinator._async_update_data()

    assert data == {"status": {}}
    mock_sign_in.assert_called_once_with("user", "pass")
    assert [call.args[0] for call in mock_device_info.await_args_list] == [
        "revoked.jwt",
        "fresh.jwt",
    ]


@pytest.mark.asyncio
@patch(f"{COORDINATOR}.edilkamin.sign_in", return_value="fresh.jwt")
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_retry_only_once(mock_device_info, mock_sign_in, coordinator):
    mock_device_info.side_effect = [http_error(401), http_error(401)]

    with pytest.raises(UpdateFailed, match="HTTP 401"):
        await coordinator._async_update_data()

    assert mock_device_info.await_count == 2
    mock_sign_in.assert_called_once()


@pytest.mark.asyncio
@patch(f"{COORDINATOR}.edilkamin.sign_in")
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_server_error_is_not_retried(mock_device_info, mock_sign_in, coordinator):
    mock_device_info.side_effect = http_error(500)

    with pytest.raises(UpdateFailed, match="HTTP 500"):
        await coordinator._async_update_data()

    mock_device_info.assert_awaited_once()
    mock_sign_in.assert_not_called()


@pytest.mark.asyncio
@patch(f"{COORDINATOR}.edilkamin.sign_in", side_effect=NotAuthorizedException("bad"))
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_invalid_credentials_raise_auth_failed(
    mock_device_info, mock_sign_in, coordinator
):
    """A changed password raises ConfigEntryAuthFailed (HA starts a reauth)."""
    mock_device_info.side_effect = http_error(401)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    mock_sign_in.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx.ConnectError("down"), "Cannot reach the Edilkamin cloud"),
        (TimeoutError(), "Cannot reach the Edilkamin cloud"),
        (ValueError("not json"), "Unexpected response format"),
    ],
)
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_errors_are_classified(mock_device_info, coordinator, error, message):
    mock_device_info.side_effect = error

    with pytest.raises(UpdateFailed, match=message):
        await coordinator._async_update_data()


@pytest.mark.asyncio
@patch(f"{COORDINATOR}.edilkamin.device_info", new_callable=AsyncMock)
async def test_non_dict_response_is_a_format_error(mock_device_info, coordinator):
    mock_device_info.return_value = ["unexpected"]

    with pytest.raises(UpdateFailed, match="Unexpected response format"):
        await coordinator._async_update_data()


def test_is_invalid_credentials_error():
    class ClientError(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    assert is_invalid_credentials_error(NotAuthorizedException())
    assert is_invalid_credentials_error(ClientError("NotAuthorizedException"))
    assert is_invalid_credentials_error(ClientError("UserNotFoundException"))
    assert not is_invalid_credentials_error(ClientError("TooManyRequestsException"))
    assert not is_invalid_credentials_error(httpx.ConnectError("down"))


@pytest.mark.asyncio
async def test_command_retries_once_after_401():
    tokens = iter(["revoked.jwt", "fresh.jwt"])
    invalidator = Mock()
    api = EdilkaminAsyncApi(
        MAC,
        "user",
        "pass",
        DummyHass(),
        token_provider=AsyncMock(side_effect=lambda: next(tokens)),
        token_invalidator=invalidator,
    )
    payload = {"name": "power", "value": 1}

    with patch(f"{API}.edilkamin.mqtt_command", new_callable=AsyncMock) as mock_cmd:
        mock_cmd.side_effect = [http_error(401), "executed"]
        result = await api.execute_command(payload)

    assert result == "executed"
    invalidator.assert_called_once()
    assert [call.args for call in mock_cmd.await_args_list] == [
        ("revoked.jwt", MAC, payload),
        ("fresh.jwt", MAC, payload),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_on", [True, False])
async def test_standby_sends_a_single_request(turn_on):
    """Standby uses the coordinator data: one mqtt/command, no device/info."""
    api = EdilkaminAsyncApi(
        MAC, "user", "pass", DummyHass(), token_provider=AsyncMock(return_value="t")
    )
    coordinator = Mock()
    coordinator.get_mac_address = Mock(return_value=MAC)
    coordinator.get_standby_waiting_time = Mock(return_value=120)
    coordinator.is_auto = Mock(return_value=True)
    coordinator.async_refresh_after_command = AsyncMock()
    switch = EdilkaminStandByModeSwitch(api, coordinator)
    switch.async_write_ha_state = Mock()

    with (
        patch(f"{API}.edilkamin.mqtt_command", new_callable=AsyncMock) as mock_cmd,
        patch(f"{API}.edilkamin.device_info", new_callable=AsyncMock) as mock_info,
    ):
        if turn_on:
            await switch.async_turn_on()
        else:
            await switch.async_turn_off()

    mock_cmd.assert_awaited_once_with(
        "t", MAC, {"name": "standby_mode", "value": turn_on}
    )
    mock_info.assert_not_called()


@pytest.mark.asyncio
async def test_standby_refused_outside_auto_mode():
    api = EdilkaminAsyncApi(MAC, "user", "pass", DummyHass())
    with pytest.raises(NotInRightStateError):
        await api.enable_standby_mode(is_auto=False)


@pytest.mark.asyncio
async def test_command_with_invalid_credentials_starts_reauth():
    coordinator = Mock()
    coordinator.get_mac_address = Mock(return_value=MAC)
    coordinator.get_standby_waiting_time = Mock(return_value=120)
    coordinator.is_auto = Mock(return_value=True)
    api = Mock()
    api.enable_standby_mode = AsyncMock(side_effect=ConfigEntryAuthFailed("bad"))
    switch = EdilkaminStandByModeSwitch(api, coordinator)
    switch.hass = Mock()

    with pytest.raises(HomeAssistantError):
        await switch.async_turn_on()

    coordinator.config_entry.async_start_reauth.assert_called_once_with(switch.hass)


class TestReauthFlow:
    @pytest.fixture
    def flow(self):
        entry = Mock()
        entry.data = {"mac_address": MAC, "username": "user", "password": "old"}
        flow = ConfigFlow()
        flow.hass = Mock()
        flow._get_reauth_entry = Mock(return_value=entry)
        flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
        flow.async_show_form = Mock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_reauth_shows_form(self, flow):
        result = await flow.async_step_reauth({})

        assert result == {"type": "form"}
        kwargs = flow.async_show_form.call_args.kwargs
        assert kwargs["step_id"] == "reauth_confirm"
        assert kwargs["errors"] == {}
        assert kwargs["description_placeholders"] == {"username": "user"}

    @pytest.mark.asyncio
    async def test_wrong_password_shows_error(self, flow):
        with patch.object(EdilkaminAsyncApi, "authenticate", return_value=False):
            await flow.async_step_reauth_confirm({"password": "wrong"})

        assert flow.async_show_form.call_args.kwargs["errors"] == {
            "base": "invalid_auth"
        }
        flow.async_update_reload_and_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_password_updates_and_reloads_entry(self, flow):
        with patch.object(EdilkaminAsyncApi, "authenticate", return_value=True):
            result = await flow.async_step_reauth_confirm({"password": "new"})

        assert result == {"type": "abort"}
        flow.async_update_reload_and_abort.assert_called_once_with(
            flow._get_reauth_entry.return_value, data_updates={"password": "new"}
        )
