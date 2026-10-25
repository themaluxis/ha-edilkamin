import asyncio
from datetime import UTC, datetime, timedelta
import logging
import time

import edilkamin
from homeassistant.core import CALLBACK_TYPE, HassJob
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import httpx
import jwt

from .const import (
    CHECK_COOLDOWN,
    CHECK_DELAY,
    STALE_AFTER,
    UNAVAILABLE_AFTER,
    UPDATE_INTERVAL,
    UPDATE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class EdilkaminCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(
        self,
        hass,
        username: str,
        password: str,
        mac_address: str,
        config_entry=None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"Edilkamin coordinator {mac_address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self._username = username
        self._password = password
        self._mac_address = mac_address

        self._token = None
        self._device_info = {}

        self._stale_after = STALE_AFTER
        self._check_delay = CHECK_DELAY
        self._check_cooldown = CHECK_COOLDOWN
        self._unavailable_after = UNAVAILABLE_AFTER
        # time.monotonic() of the last "check" command sent, None if never sent
        self._last_check_sent: float | None = None
        # Outcome of the last "check" command, None if never sent
        self.last_check_success: bool | None = None
        self.last_check_time: datetime | None = None
        # Cancels the refresh planned after a command, None when nothing planned
        self._unsub_command_refresh: CALLBACK_TYPE | None = None

    async def refresh_token(self) -> str:
        """Refresh the token only if expired."""
        _LOGGER.debug("Refreshing token")
        if self._token is None or self.is_token_expired(self._token):
            _LOGGER.debug("Token is expired or None, signing in again")
            self._token = await self.hass.async_add_executor_job(
                edilkamin.sign_in, self._username, self._password
            )
            _LOGGER.debug("Token refreshed")
        else:
            _LOGGER.debug("Token is still valid, using existing one")

        return self._token

    def is_token_expired(self, token: str) -> bool:
        """Check if the token is expired."""
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            exp = payload.get("exp")
            if exp is None:
                return True
            exp_date = datetime.fromtimestamp(exp, tz=UTC)
            # Add a buffer of 60 seconds to the expiration time
            return exp_date < datetime.now(tz=UTC) + timedelta(seconds=60)
        except (jwt.PyJWTError, KeyError):
            return True
        except Exception:  # noqa: BLE001
            return True

    async def update_device_information(self) -> None:
        """Get the latest data and update the relevant Entity attributes."""
        self._token = await self.refresh_token()
        return await edilkamin.device_info(self._token, self._mac_address)

    async def _async_update_data(self):
        """Fetch data from the API, asking the stove to publish when stale."""
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT):
                data = await self.update_device_information()
                age = self.compute_data_age(data)
                if age is not None and age > self._stale_after:
                    data = await self._async_refresh_stale_data(data, age)
        except Exception as e:
            msg = "Error communicating with API"
            raise UpdateFailed(msg) from e

        self._device_info = data
        _LOGGER.debug("Data updated successfully")
        _LOGGER.debug(self._device_info)
        return self._device_info

    async def _async_refresh_stale_data(self, data: dict, age: float) -> dict:
        """Send a check and read device/info again, within the check cooldown."""
        if not self.can_send_check():
            _LOGGER.debug(
                "Data is %.0f s old but a check was sent less than %s s ago",
                age,
                self._check_cooldown,
            )
            return data

        _LOGGER.debug("Data is %.0f s old, asking the stove to publish", age)
        if not await self.async_send_check():
            return data

        await asyncio.sleep(self._check_delay)
        data = await self.update_device_information()
        age = self.compute_data_age(data)
        if age is not None and age > self._stale_after:
            _LOGGER.warning(
                "Edilkamin cloud data is still %.0f s old after a check command",
                age,
            )
        return data

    async def async_refresh_after_command(self) -> None:
        """Make the stove publish after a command, then refresh a bit later.

        device/info only returns the state last published by the stove, so an
        immediate refresh would read the state from before the command. Commands
        sent close together re-arm the same timer: a burst of commands gives a
        single delayed refresh.
        """
        if self.can_send_check():
            await self.async_send_check()

        if self._unsub_command_refresh is not None:
            self._unsub_command_refresh()
        self._unsub_command_refresh = async_call_later(
            self.hass,
            self._check_delay,
            HassJob(self._async_command_refresh, cancel_on_shutdown=True),
        )

    async def _async_command_refresh(self, _now: datetime) -> None:
        """Refresh planned by async_refresh_after_command."""
        self._unsub_command_refresh = None
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        """Cancel the planned refresh, then stop the coordinator."""
        if self._unsub_command_refresh is not None:
            self._unsub_command_refresh()
            self._unsub_command_refresh = None
        await super().async_shutdown()

    def can_send_check(self) -> bool:
        """Return True when the check cooldown is over."""
        return (
            self._last_check_sent is None
            or time.monotonic() - self._last_check_sent >= self._check_cooldown
        )

    async def async_send_check(self) -> bool:
        """Ask the stove to publish its state again. Return True on success."""
        self._last_check_sent = time.monotonic()
        self.last_check_time = datetime.now(tz=UTC)
        try:
            token = await self.refresh_token()
            await edilkamin.mqtt_command(token, self._mac_address, {"name": "check"})
        except httpx.HTTPError as err:
            self.last_check_success = False
            _LOGGER.warning("Check command to the stove failed: %s", err)
            return False

        self.last_check_success = True
        return True

    @staticmethod
    def get_status_timestamp_from(
        data: dict | None, block: str = "status"
    ) -> float | None:
        """Return the timestamp of a block ("status" or "nvm"), in seconds."""
        timestamp = ((data or {}).get(block) or {}).get("timestamp")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            return None
        # status.timestamp is in milliseconds, accept seconds just in case
        return timestamp / 1000 if timestamp > 1e11 else float(timestamp)

    def compute_data_age(self, data: dict | None) -> float | None:
        """Return the age in seconds of a device/info payload."""
        timestamp = self.get_status_timestamp_from(data)
        if timestamp is None:
            return None
        return time.time() - timestamp

    def get_status_timestamp(self, block: str = "status") -> float | None:
        """Return the time the stove last published a block, in seconds."""
        return self.get_status_timestamp_from(self._device_info, block)

    def get_data_age(self) -> float | None:
        """Return how old the current data is, in seconds."""
        return self.compute_data_age(self._device_info)

    def is_data_too_old(self) -> bool:
        """Return True when entities should be marked unavailable."""
        age = self.get_data_age()
        return age is not None and age > self._unavailable_after

    def get_token(self) -> str:
        """Return the current token."""
        return self._token

    def get_mac_address(self) -> str:
        """Return the MAC address."""
        return self._mac_address

    def get_temperatures(self) -> dict:
        """Get the temperatures mapping reported by the device."""
        return (self._device_info.get("status") or {}).get("temperatures") or {}

    def get_temperature(self) -> float | None:
        """Get the environment temperature."""
        return self.get_temperatures().get("enviroment")

    def get_water_temperature(self, key: str) -> float | None:
        """Get a hydronic water temperature (e.g. puffer, boiler) by key."""
        return self.get_temperatures().get(key)

    def get_fan_speed(self, index: int = 1) -> str:
        """Get the fan speed."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get(f"fan_{index}_ventilation")
        )

    def get_nb_fans(self) -> int:
        """Get the number of fans."""
        return (
            self._device_info.get("nvm", {})
            .get("installer_parameters", {})
            .get("fans_number", 0)
        )

    def get_nb_alarms(self) -> int:
        """Get the number of alarms."""
        return self._device_info.get("nvm", {}).get("alarms_log", {}).get("index", 0)

    def get_alarms(self) -> list:
        """Get the alarms."""
        alarms_info = self._device_info.get("nvm", {}).get("alarms_log", {})
        index = alarms_info.get("index", 0)
        alarms = alarms_info.get("alarms", [])
        return [alarms[i] for i in range(min(index, len(alarms)))]

    def get_actual_power(self) -> str | None:
        """Get the actual power."""
        return self._device_info.get("status", {}).get("state", {}).get("actual_power")

    def get_status_tank(self) -> str | None:
        """Get the status of the tank."""
        return (
            self._device_info.get("status", {})
            .get("flags", {})
            .get("is_pellet_in_reserve")
        )

    def get_airkare_status(self) -> str:
        """Get the status of the airkare."""
        return (
            self._device_info.get("status", {})
            .get("flags", {})
            .get("is_airkare_active")
        )

    def get_power_status(self) -> str:
        """Get the status of the power."""
        return self._device_info.get("status", {}).get("commands", {}).get("power")

    def get_relax_status(self) -> str:
        """Get the status of the relax."""
        return (
            self._device_info.get("status", {}).get("flags", {}).get("is_relax_active")
        )

    def get_target_temperature(self) -> str:
        """Get the target temperature."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get("enviroment_1_temperature")
        )

    def get_chrono_mode_status(self) -> str:
        """Get the status of the chrono mode."""
        return self._device_info.get("nvm", {}).get("chrono", {}).get("is_active")

    def get_operational_phase(self) -> str:
        """Get the operational phase."""
        return (
            self._device_info.get("status", {})
            .get("state", {})
            .get("operational_phase")
        )

    def get_autonomy_second(self) -> str | None:
        """Get the autonomy time."""
        return (
            self._device_info.get("status", {})
            .get("pellet", {})
            .get("autonomy_time", None)
        )

    def get_standby_mode(self) -> bool:
        """Get standby mode."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get("is_standby_active", False)
        )

    def get_standby_waiting_time(self) -> str | None:
        """Get standby waiting time."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get("standby_waiting_time", None)
        )

    def get_power_ons(self) -> str | None:
        """Get the number of power ons."""
        return (
            self._device_info.get("nvm", {})
            .get("total_counters", {})
            .get("power_ons", None)
        )

    def is_auto(self) -> bool:
        """Check if the device is in auto mode."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get("is_auto", False)
        )

    def get_manual_power(self):
        """Get the manual mode."""
        return (
            self._device_info.get("nvm", {})
            .get("user_parameters", {})
            .get("manual_power")
        )
