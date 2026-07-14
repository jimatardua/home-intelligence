"""Config flow for Rocky Mountain Power."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import CannotConnect, InvalidAuth, RockyMountainPowerClient
from .const import DOMAIN, LOGGER

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _validate_login(username: str, password: str) -> None:
    """Blocking: log in and resolve account identifiers, or raise.

    Runs in the executor -- api.py is deliberately synchronous, see its
    module docstring.
    """
    client = RockyMountainPowerClient(username, password)
    try:
        client.get_metered_agreements()
    finally:
        client.close()


class RockyMountainPowerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rocky Mountain Power."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-step username/password form, validated against the live API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(
                    _validate_login, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - guard against unexpected shape changes
                LOGGER.exception("Unexpected exception validating Rocky Mountain Power login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )
