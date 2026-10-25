"""Config flow for Edilkamin integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError
import macaddress
import voluptuous as vol

from custom_components.edilkamin.api.edilkamin_async_api import EdilkaminAsyncApi

from .const import DOMAIN, MAC_ADDRESS, PASSWORD, USERNAME

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(MAC_ADDRESS): str,
        vol.Required(USERNAME): str,
        vol.Required(PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(PASSWORD): str})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Edilkamin."""

    VERSION = 2

    async def async_step_user(self, user_input):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac_address = user_input[MAC_ADDRESS]

            try:
                macaddress.MAC(mac_address)
            except ValueError:
                _LOGGER.exception("Invalid mac address: %s", mac_address)
                errors["base"] = "mac_address"
                return self.async_show_form(
                    step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
                )

            # Check if a stove with the same mac address is already configured
            await self.async_set_unique_id(mac_address)
            self._abort_if_unique_id_configured()

            username = user_input[USERNAME]
            password = user_input[PASSWORD]
            api = EdilkaminAsyncApi(
                mac_address=mac_address,
                username=username,
                password=password,
                hass=self.hass,
            )
            try:
                if await api.authenticate():
                    return self.async_create_entry(
                        title=mac_address.replace(":", ""), data=user_input
                    )

                errors["base"] = "invalid_auth"
            except Exception as exception:
                _LOGGER.exception("Exception message: %s, type=%s")
                if exception.__class__.__name__ == "NotAuthorizedException":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, _entry_data: Mapping[str, Any]):
        """Start a reauthentication after the credentials were refused."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for the new password and check it before updating the entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        username = entry.data[USERNAME]

        if user_input is not None:
            api = EdilkaminAsyncApi(
                mac_address=entry.data[MAC_ADDRESS],
                username=username,
                password=user_input[PASSWORD],
                hass=self.hass,
            )
            if await api.authenticate():
                return self.async_update_reload_and_abort(
                    entry, data_updates={PASSWORD: user_input[PASSWORD]}
                )
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"username": username},
        )


class InvalidMacAddressError(HomeAssistantError):
    """Error to indicate there is invalid mac address."""
