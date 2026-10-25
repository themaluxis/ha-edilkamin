from collections.abc import Awaitable, Callable
import logging
from typing import Any

import edilkamin
from homeassistant.core import HomeAssistant
import httpx

_LOGGER = logging.getLogger(__name__)

# HTTP statuses returned by the cloud when the token is no longer accepted
AUTH_ERROR_STATUSES = (401, 403)
# Cognito errors meaning the username or password is wrong
INVALID_CREDENTIALS_ERRORS = ("NotAuthorizedException", "UserNotFoundException")


def is_invalid_credentials_error(err: BaseException) -> bool:
    """Return True when a sign in error means the credentials are wrong."""
    if type(err).__name__ in INVALID_CREDENTIALS_ERRORS:
        return True
    response = getattr(err, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code") in INVALID_CREDENTIALS_ERRORS
    return False


async def call_with_reauth(
    get_token: Callable[[], Awaitable[str]],
    invalidate_token: Callable[[], None],
    func: Callable[..., Awaitable[Any]],
    *args: Any,
) -> Any:
    """Call ``func(token, *args)``, signing in again once if the token is refused."""
    token = await get_token()
    try:
        return await func(token, *args)
    except httpx.HTTPStatusError as err:
        if err.response.status_code not in AUTH_ERROR_STATUSES:
            raise
        _LOGGER.info(
            "Edilkamin cloud refused the token (HTTP %s), signing in again",
            err.response.status_code,
        )
    invalidate_token()
    token = await get_token()
    return await func(token, *args)


class EdilkaminAsyncApi:
    """Class to interact with the Edilkamin API."""

    def __init__(  # noqa: PLR0913
        self,
        mac_address,
        username: str,
        password: str,
        hass: HomeAssistant,
        token_provider: Callable[[], Awaitable[str]] | None = None,
        token_invalidator: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the class.

        ``token_provider`` lets the wrapper reuse an already cached token
        (e.g. the coordinator's) instead of signing in on every call, and
        ``token_invalidator`` drops it when the cloud refuses it.
        """
        self._hass = hass
        self._mac_address = mac_address
        self._username = username
        self._password = password
        self._token_provider = token_provider
        self._token_invalidator = token_invalidator

    def get_mac_address(self):
        """Get the mac address."""
        return self._mac_address

    async def authenticate(self) -> bool:
        try:
            await self._hass.async_add_executor_job(
                edilkamin.sign_in, self._username, self._password
            )
        except Exception:  # noqa: BLE001
            return False
        else:
            return True

    async def set_temperature(self, value):
        """Modify the temperature."""
        await self.execute_command({"name": "enviroment_1_temperature", "value": value})

    async def enable_power(self):
        """Set the power status to on."""
        await self.execute_command({"name": "power", "value": 1})

    async def disable_power(self):
        """Set the power status to off."""
        await self.execute_command({"name": "power", "value": 0})

    async def enable_chrono_mode(self):
        """Enable the chrono mode."""
        await self.execute_command({"name": "chrono_mode", "value": True})

    async def disable_chrono_mode(self):
        """Disable the chono mode."""
        await self.execute_command({"name": "chrono_mode", "value": False})

    async def enable_airkare(self):
        """Enable airkare."""
        await self.execute_command({"name": "airkare_function", "value": 1})

    async def disable_airkare(self):
        """Disable airkare."""
        await self.execute_command({"name": "airkare_function", "value": 0})

    async def enable_relax(self):
        """Enable relax."""
        await self.execute_command({"name": "relax_mode", "value": True})

    async def disable_relax(self):
        """Disable relax."""
        await self.execute_command({"name": "relax_mode", "value": False})

    async def set_fan_speed(self, value, index=1):
        """Set the speed of fan 1."""
        await self.execute_command(
            {"name": "fan_" + str(index) + "_speed", "value": int(value)}
        )

    async def check(self):
        """Call check config."""
        await self.execute_command({"name": "check", "value": False})

    async def get_token(self):
        """Return a valid token, reusing the shared provider when available."""
        if self._token_provider is not None:
            return await self._token_provider()
        return await self._hass.async_add_executor_job(
            edilkamin.sign_in, self._username, self._password
        )

    def invalidate_token(self) -> None:
        """Drop the shared token so the next call signs in again."""
        if self._token_invalidator is not None:
            self._token_invalidator()

    async def get_info(self):
        """Get the device information."""
        return await call_with_reauth(
            self.get_token,
            self.invalidate_token,
            edilkamin.device_info,
            self._mac_address,
        )

    async def enable_standby_mode(self, *, is_auto: bool):
        """Set the standby mode, only allowed in auto mode.

        ``is_auto`` comes from the data already read by the coordinator.
        """
        if not is_auto:
            raise NotInRightStateError

        await self.execute_command({"name": "standby_mode", "value": True})

    async def disable_standby_mode(self, *, is_auto: bool):
        """Unset the standby mode, only allowed in auto mode."""
        if not is_auto:
            raise NotInRightStateError

        await self.execute_command({"name": "standby_mode", "value": False})

    async def enable_auto_mode(self):
        """Set the auto mode."""
        await self.execute_command({"name": "auto_mode", "value": True})

    async def disable_auto_mode(self):
        """Set the auto mode."""
        await self.execute_command({"name": "auto_mode", "value": False})

    async def set_manual_power_level(self, value: int):
        """Set the manual power level."""
        await self.execute_command({"name": "power_level", "value": value})

    async def execute_command(self, payload: dict) -> str:
        """Execute the command."""
        _LOGGER.debug("Execute command with payload = %s", payload)
        return await call_with_reauth(
            self.get_token,
            self.invalidate_token,
            edilkamin.mqtt_command,
            self._mac_address,
            payload,
        )


class HttpError(Exception):
    """HTTP exception class with message text, and status code."""

    def __init__(self, message, text, status_code) -> None:
        """Initialize the class."""
        super().__init__(message)
        self.status_code = status_code
        self.text = text


class EdilkaminApiError(Exception):
    """Base class for exceptions in this module."""


class NotInRightStateError(EdilkaminApiError):
    """Exception raised when the device is not in the right state."""

    def __init__(self):
        super().__init__("Standby mode is only available from auto mode.")
