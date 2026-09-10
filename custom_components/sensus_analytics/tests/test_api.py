"""Tests for api.py's SensusAnalyticsClient.

`api.py`/`const.py` are plain, HA-independent Python (neither imports
anything from `homeassistant`), but a normal `from
custom_components.sensus_analytics import api` would still execute the
real package `__init__.py` first (importing a submodule always imports
its parent package), which needs the real `homeassistant` framework --
not installed in this dev environment, and not needed to test HTTP/JSON
logic that never touches HA at all. So `api.py`/`const.py` are loaded
directly from their file paths under a synthetic module name unrelated to
the real `custom_components.*` dotted path, sidestepping the real
`__init__.py` entirely -- the exact same technique
`custom_components/rocky_mountain_power/tests/test_api.py` already uses
in this repo, for the identical reason.

Run with (matching that file's own documented pinned-rootdir requirement):

    python -m pytest custom_components/sensus_analytics/tests/test_api.py \\
        -q --import-mode=importlib --rootdir=custom_components/sensus_analytics/tests

Pure mocking of `requests.Session`, no network calls, no real credentials.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_COMPONENT_DIR = Path(__file__).resolve().parent.parent
_STUB_PKG = "_sensus_analytics_under_test"


def _load_stub_submodule(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{_STUB_PKG}.{name}", _COMPONENT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _STUB_PKG
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if _STUB_PKG not in sys.modules:
    stub_pkg = types.ModuleType(_STUB_PKG)
    stub_pkg.__path__ = [str(_COMPONENT_DIR)]
    sys.modules[_STUB_PKG] = stub_pkg
    _load_stub_submodule("const")
    _api = _load_stub_submodule("api")
else:
    _api = sys.modules[f"{_STUB_PKG}.api"]

CannotConnect = _api.CannotConnect
InvalidAuth = _api.InvalidAuth
UnexpectedResponse = _api.UnexpectedResponse
SensusAnalyticsClient = _api.SensusAnalyticsClient

BASE_URL = "https://my-slc.sensus-analytics.com"

# The confirmed real response shape for the daily-usage widget (see
# api.py's docstring / the HA community thread that first reverse-
# engineered this API).
DAILY_WIDGET_RESPONSE = {
    "widgetList": [
        {
            "data": {
                "devices": [
                    {
                        "dailyUsage": 42,
                        "usageUnit": "GAL",
                        "meterId": "ABC123",
                        "meterAddress1": "123 Main St",
                        "lastRead": 1735689600000,
                        "latestReadUsage": 987654,
                        "billingUsage": 3000,
                    }
                ]
            }
        }
    ]
}

# The confirmed real hourly shape: first element is a units header, the
# rest are [timestamp_ms, usage, rain, temp] entries.
HOURLY_RESPONSE = {
    "operationSuccess": True,
    "data": {
        "usage": [
            ["GAL", "INCHES", "FAHRENHEIT"],
            [1735689600000, 12, 0.0, 68.5],
            [1735693200000, 8, 0.02, 67.1],
        ]
    },
}


def _mock_response(status_code=200, json_data=None, raise_for_status_error=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if raise_for_status_error:
        resp.raise_for_status.side_effect = raise_for_status_error
    else:
        resp.raise_for_status.return_value = None
    return resp


# --- login ------------------------------------------------------------


def test_login_succeeds_on_302():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "post", return_value=_mock_response(status_code=302)) as mock_post:
        client.login()  # does not raise

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://my-slc.sensus-analytics.com/j_spring_security_check"
    assert kwargs["data"] == {"j_username": "user", "j_password": "pw"}
    assert kwargs["allow_redirects"] is False


def test_login_raises_invalid_auth_on_non_302():
    client = SensusAnalyticsClient(BASE_URL, "user", "wrong-pw")
    with patch.object(client._session, "post", return_value=_mock_response(status_code=200)):
        with pytest.raises(InvalidAuth):
            client.login()


def test_login_raises_cannot_connect_on_network_error():
    import requests

    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "post", side_effect=requests.exceptions.ConnectionError("no route")):
        with pytest.raises(CannotConnect):
            client.login()


def test_base_url_trailing_slash_is_normalized():
    client_no_slash = SensusAnalyticsClient("https://example.com", "u", "p")
    client_with_slash = SensusAnalyticsClient("https://example.com/", "u", "p")

    with patch.object(client_no_slash._session, "post", return_value=_mock_response(302)) as m1:
        client_no_slash.login()
    with patch.object(client_with_slash._session, "post", return_value=_mock_response(302)) as m2:
        client_with_slash.login()

    assert m1.call_args[0][0] == m2.call_args[0][0] == "https://example.com/j_spring_security_check"


# --- get_daily_data -----------------------------------------------------


def test_get_daily_data_unwraps_the_confirmed_response_shape():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "post", return_value=_mock_response(200, DAILY_WIDGET_RESPONSE)):
        data = client.get_daily_data("ACCT1", "METER1")

    assert data["dailyUsage"] == 42
    assert data["usageUnit"] == "GAL"
    assert data["meterId"] == "ABC123"


def test_get_daily_data_sends_correct_payload():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "post", return_value=_mock_response(200, DAILY_WIDGET_RESPONSE)) as mock_post:
        client.get_daily_data("ACCT1", "METER1")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://my-slc.sensus-analytics.com/water/widget/byPage"
    assert kwargs["json"] == {"group": "meters", "accountNumber": "ACCT1", "deviceId": "METER1"}


def test_get_daily_data_raises_unexpected_response_on_malformed_shape():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "post", return_value=_mock_response(200, {"widgetList": []})):
        with pytest.raises(UnexpectedResponse):
            client.get_daily_data("ACCT1", "METER1")


def test_get_daily_data_raises_cannot_connect_on_http_error():
    import requests

    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(
        client._session,
        "post",
        return_value=_mock_response(500, None, raise_for_status_error=requests.exceptions.HTTPError("500")),
    ):
        with pytest.raises(CannotConnect):
            client.get_daily_data("ACCT1", "METER1")


# --- get_hourly_data_raw -------------------------------------------------


def test_get_hourly_data_raw_returns_decoded_json():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "get", return_value=_mock_response(200, HOURLY_RESPONSE)):
        data = client.get_hourly_data_raw("ACCT1", "METER1", 1735689600000, 1735776000000)

    assert data == HOURLY_RESPONSE


def test_get_hourly_data_raw_uses_correct_url_and_params():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    with patch.object(client._session, "get", return_value=_mock_response(200, HOURLY_RESPONSE)) as mock_get:
        client.get_hourly_data_raw("ACCT1", "METER1", 1000, 2000)

    args, kwargs = mock_get.call_args
    assert args[0] == "https://my-slc.sensus-analytics.com/water/usage/ACCT1/METER1"
    assert kwargs["params"] == {"start": 1000, "end": 2000, "zoom": "day", "page": "null", "weather": "1"}


def test_get_hourly_data_raw_raises_unexpected_response_on_non_json():
    client = SensusAnalyticsClient(BASE_URL, "user", "pw")
    resp = _mock_response(200)
    resp.json.side_effect = ValueError("not json")
    with patch.object(client._session, "get", return_value=resp):
        with pytest.raises(UnexpectedResponse):
            client.get_hourly_data_raw("ACCT1", "METER1", 1000, 2000)
