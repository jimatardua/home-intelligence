"""Config flow for the Sensus Analytics integration.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md. Three changes from the original fork:

1. The password field is a masked `selector.TextSelector` in both the
   setup and options forms, not a bare `str` -- the original showed the
   password in plaintext as you typed it, and the options form pre-filled
   your actual password back into that same unmasked field as its visible
   default.
2. Credential validation calls into api.py's `SensusAnalyticsClient`
   (matching custom_components/rocky_mountain_power's `_validate_login`
   pattern in this repo) instead of a second, separate `aiohttp`-based
   login implementation duplicating coordinator.py's `requests`-based one.
3. The `is_matching()` override (`return False` with a "implement if
   necessary" comment) is removed -- this flow has no discovery source
   (Bluetooth/Zeroconf/etc.), only a user-initiated step, so HA never
   actually calls it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv, selector

from .api import CannotConnect, InvalidAuth, SensusAnalyticsClient
from .const import CONF_ACCOUNT_NUMBER, CONF_BASE_URL, CONF_METER_NUMBER, DOMAIN, LOGGER

DEFAULT_TITLE = "Sensus Analytics"

_PASSWORD_SELECTOR = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def _credentials_and_pricing_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Shared field set for both the initial setup and the options flow.

    Deliberately still one flat schema mixing API credentials with the
    billing tier/pricing fields, matching the original fork -- splitting
    those into a separate concern (mirroring energy_report's
    billing.py/tariffs.py split elsewhere in this repo) is a real possible
    improvement but out of scope for this patch; see
    docs/sensus-analytics-water.md.
    """
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_BASE_URL, default=defaults.get(CONF_BASE_URL)): str,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME)): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD)): _PASSWORD_SELECTOR,
            vol.Required(CONF_ACCOUNT_NUMBER, default=defaults.get(CONF_ACCOUNT_NUMBER)): str,
            vol.Required(CONF_METER_NUMBER, default=defaults.get(CONF_METER_NUMBER)): str,
            vol.Required("unit_type", default=defaults.get("unit_type", "CCF")): vol.In(["CCF", "gal"]),
            vol.Optional("tier1_gallons", default=defaults.get("tier1_gallons")): cv.positive_float,
            vol.Required("tier1_price", default=defaults.get("tier1_price", 0.0128)): cv.positive_float,
            vol.Optional("tier2_gallons", default=defaults.get("tier2_gallons")): cv.positive_float,
            vol.Optional("tier2_price", default=defaults.get("tier2_price")): cv.positive_float,
            vol.Optional("tier3_price", default=defaults.get("tier3_price")): cv.positive_float,
            vol.Required("service_fee", default=defaults.get("service_fee", 15.00)): cv.positive_float,
        }
    )


def _validate_login(base_url: str, username: str, password: str) -> None:
    """Blocking: log in, or raise InvalidAuth/CannotConnect.

    Runs in the executor -- api.py is deliberately synchronous, same
    convention as rocky_mountain_power's own `_validate_login` in this
    repo.
    """
    client = SensusAnalyticsClient(base_url, username, password)
    try:
        client.login()
    finally:
        client.close()


class SensusAnalyticsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Sensus Analytics integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = f"{user_input[CONF_ACCOUNT_NUMBER]}_{user_input[CONF_METER_NUMBER]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(
                    _validate_login,
                    user_input[CONF_BASE_URL],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - guard against unexpected shape changes
                LOGGER.exception("Unexpected exception validating Sensus Analytics login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=DEFAULT_TITLE, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_credentials_and_pricing_schema(user_input), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SensusAnalyticsOptionsFlow:
        """Get the options flow for this handler."""
        return SensusAnalyticsOptionsFlow()


class SensusAnalyticsOptionsFlow(config_entries.OptionsFlow):
    """Handle Sensus Analytics options.

    Re-validates credentials the same way the initial setup does --
    the original fork's options flow updated the config entry's data
    directly with no validation at all, so a typo'd password here would
    silently break polling instead of being caught immediately.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    _validate_login,
                    user_input[CONF_BASE_URL],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception validating Sensus Analytics login")
                errors["base"] = "unknown"
            else:
                # Reload picks up the new credentials/options via
                # __init__.py's update listener -- this replaces the
                # original fork's manual async_request_refresh() on the
                # *existing* coordinator/client, which never actually
                # picked up a changed username/password since it kept
                # reusing the old client instance.
                self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_credentials_and_pricing_schema(user_input or dict(self.config_entry.data)),
            errors=errors,
        )
