"""The Edilkamin integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from custom_components.edilkamin.api.edilkamin_async_api import EdilkaminAsyncApi

from .const import MAC_ADDRESS, PASSWORD, USERNAME
from .coordinator import EdilkaminCoordinator
from .data import EdilkaminConfigEntry, EdilkaminData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.SENSOR,
    Platform.SWITCH,
]


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: EdilkaminConfigEntry) -> bool:
    """Set up Edilkamin from a config entry."""

    mac_address = entry.data[MAC_ADDRESS]
    username = entry.data[USERNAME]
    password = entry.data[PASSWORD]

    coordinator = EdilkaminCoordinator(
        hass, username, password, mac_address, config_entry=entry
    )

    # Raises ConfigEntryNotReady when the cloud is unreachable, HA retries later
    await coordinator.async_config_entry_first_refresh()

    api = EdilkaminAsyncApi(
        mac_address=mac_address,
        username=username,
        password=password,
        hass=hass,
        token_provider=coordinator.refresh_token,
    )
    entry.runtime_data = EdilkaminData(coordinator=coordinator, api=api)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EdilkaminConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()
    return unload_ok
