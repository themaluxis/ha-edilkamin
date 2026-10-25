"""Base entity shared by all Edilkamin coordinator entities."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.edilkamin_async_api import EdilkaminApiError
from .const import DOMAIN, OPTIMISTIC_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Awaitable

_LOGGER = logging.getLogger(__name__)


class EdilkaminEntity(CoordinatorEntity):
    """Common behaviour of the Edilkamin entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator) -> None:
        """Initialize the entity and attach it to the stove device."""
        super().__init__(coordinator)
        self._mac_address = coordinator.get_mac_address()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._mac_address)},
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac_address)},
            manufacturer="Edilkamin",
            model="The Mind",
            name="Edilkamin Stove",
            suggested_area="Living Room",
        )
        # Attribute name -> (requested value, time.time() of the command,
        # device/info block the value is read from: "status" or "nvm")
        self._optimistic_values: dict[str, tuple[Any, float, str]] = {}

    @property
    def available(self) -> bool:
        """Return False when the cloud data is too old to be trusted."""
        return super().available and not self.coordinator.is_data_too_old()

    async def async_added_to_hass(self) -> None:
        """Read the initial state from the coordinator."""
        await super().async_added_to_hass()
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Set the entity attributes from the coordinator data."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update from the coordinator, keeping the pending optimistic values."""
        self._update_from_coordinator()
        self._optimistic_values = {
            name: pending
            for name, pending in self._optimistic_values.items()
            if not self._optimistic_value_expired(*pending)
        }
        self._apply_optimistic_values()
        self.async_write_ha_state()

    def _optimistic_value_expired(self, _value: Any, since: float, block: str) -> bool:
        """Return True once the block was published after the command."""
        if time.time() - since > OPTIMISTIC_TIMEOUT:
            return True
        published = self.coordinator.get_status_timestamp(block)
        return published is not None and published > since

    def _apply_optimistic_values(self) -> None:
        for name, (value, _since, _block) in self._optimistic_values.items():
            setattr(self, name, value)

    async def _async_send_command(
        self, command: Awaitable, block: str = "status", **optimistic_values: Any
    ) -> None:
        """Send a command, show the requested values and refresh later.

        ``block`` is the device/info block ("status" or "nvm") the values are
        read from: they are shown until that block is published after the
        command, or for OPTIMISTIC_TIMEOUT at most.
        """
        try:
            await command
        except EdilkaminApiError as err:
            raise HomeAssistantError(str(err)) from err
        except ConfigEntryAuthFailed as err:
            if self.coordinator.config_entry is not None:
                self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except Exception as err:
            _LOGGER.debug("Edilkamin command failed", exc_info=True)
            msg = f"The Edilkamin cloud rejected the command: {err}"
            raise HomeAssistantError(msg) from err

        if optimistic_values:
            now = time.time()
            for name, value in optimistic_values.items():
                self._optimistic_values[name] = (value, now, block)
            self._apply_optimistic_values()
            self.async_write_ha_state()

        await self.coordinator.async_refresh_after_command()
