"""Tests for config_flow.py.

Uses the real `homeassistant` package (see test_sensor.py's docstring for
why -- config_flow.py has genuine, unavoidable `homeassistant` imports,
unlike api.py/const.py).

This repo has no established pattern yet for exercising a full async
config-flow step against a real `hass` fixture (that needs
`pytest-homeassistant-custom-component`, not installed here, and
`custom_components/rocky_mountain_power` -- the precedent this fork
otherwise follows exactly -- has no test_config_flow.py of its own either).
So these tests stay at the level the plan actually asked for: the
standalone `_validate_login` helper (mocked client, no network), and
static inspection of the schema/class -- confirming the three fork-specific
fixes (masked password field, single validation path, dead `is_matching`
removed) rather than a full HA flow-engine integration test.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.helpers import selector

from custom_components.sensus_analytics import config_flow
from custom_components.sensus_analytics.api import CannotConnect, InvalidAuth
from custom_components.sensus_analytics.config_flow import (
    SensusAnalyticsConfigFlow,
    _credentials_and_pricing_schema,
    _validate_login,
)
from custom_components.sensus_analytics.const import CONF_ACCOUNT_NUMBER, CONF_BASE_URL, CONF_METER_NUMBER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

# --- _validate_login: delegates to SensusAnalyticsClient, closes either way ---


def test_validate_login_success_logs_in_and_closes():
    with patch.object(config_flow, "SensusAnalyticsClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        _validate_login("https://example.com", "user", "pw")

    mock_client_cls.assert_called_once_with("https://example.com", "user", "pw")
    mock_client.login.assert_called_once()
    mock_client.close.assert_called_once()


def test_validate_login_propagates_invalid_auth_and_still_closes():
    with patch.object(config_flow, "SensusAnalyticsClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.login.side_effect = InvalidAuth("bad creds")
        mock_client_cls.return_value = mock_client

        try:
            _validate_login("https://example.com", "user", "wrong")
            raised = False
        except InvalidAuth:
            raised = True

    assert raised
    mock_client.close.assert_called_once()


def test_validate_login_propagates_cannot_connect_and_still_closes():
    with patch.object(config_flow, "SensusAnalyticsClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.login.side_effect = CannotConnect("no route")
        mock_client_cls.return_value = mock_client

        try:
            _validate_login("https://example.com", "user", "pw")
            raised = False
        except CannotConnect:
            raised = True

    assert raised
    mock_client.close.assert_called_once()


# --- schema: password is masked, everything else is a plain str/positive_float ---


def _password_validator(schema: dict) -> object:
    for key, validator in schema.items():
        if str(key) == CONF_PASSWORD:
            return validator
    raise AssertionError(f"{CONF_PASSWORD!r} not found in schema keys: {list(schema)}")


def test_password_field_is_a_masked_text_selector():
    schema = _credentials_and_pricing_schema().schema
    validator = _password_validator(schema)

    assert isinstance(validator, selector.TextSelector)
    assert validator.config["type"] == selector.TextSelectorType.PASSWORD


def test_password_field_stays_masked_when_pre_filling_options_flow_defaults():
    # This is the exact original-fork bug (see NOTICE.md): the options
    # flow pre-fills the *current* config entry data -- including the
    # real password -- back into the form's defaults. Confirming the
    # field is still the masked selector (not a bare str with the
    # plaintext password as its visible default) even when a real
    # password is passed through `defaults`.
    schema = _credentials_and_pricing_schema({CONF_PASSWORD: "s3cr3t-real-password"}).schema
    validator = _password_validator(schema)

    assert isinstance(validator, selector.TextSelector)
    assert validator.config["type"] == selector.TextSelectorType.PASSWORD


def test_other_credential_fields_are_plain_str():
    schema = _credentials_and_pricing_schema().schema
    for conf_key in (CONF_BASE_URL, CONF_USERNAME, CONF_ACCOUNT_NUMBER, CONF_METER_NUMBER):
        validator = next(v for k, v in schema.items() if str(k) == conf_key)
        assert validator is str


# --- is_matching: removed, not just overridden to False ---


def test_is_matching_override_was_removed():
    assert "is_matching" not in SensusAnalyticsConfigFlow.__dict__
