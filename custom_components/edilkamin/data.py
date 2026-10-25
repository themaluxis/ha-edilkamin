"""Runtime data stored on the Edilkamin config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .api.edilkamin_async_api import EdilkaminAsyncApi
    from .coordinator import EdilkaminCoordinator


@dataclass
class EdilkaminData:
    """Objects shared by the platforms of one config entry."""

    coordinator: EdilkaminCoordinator
    api: EdilkaminAsyncApi


type EdilkaminConfigEntry = ConfigEntry[EdilkaminData]
