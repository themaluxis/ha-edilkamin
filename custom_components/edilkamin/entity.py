"""Base entity shared by all Edilkamin coordinator entities."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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

    @property
    def available(self) -> bool:
        """Return False when the cloud data is too old to be trusted."""
        return super().available and not self.coordinator.is_data_too_old()
