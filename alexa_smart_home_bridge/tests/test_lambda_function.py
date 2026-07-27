"""Unit tests for the Alexa <-> Home Assistant Lambda bridge.

Run via a scoped venv, same convention as energy_report/home_dashboard:

    alexa_smart_home_bridge/.venv/bin/python -m pytest alexa_smart_home_bridge/tests/ -q

No live AWS or Home Assistant calls -- urllib.request.urlopen is mocked
throughout.
"""

import json
import os
import sys
import urllib.error
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lambda_function  # noqa: E402


DISCOVERY_EVENT = {
    "directive": {
        "header": {
            "namespace": "Alexa.Discovery",
            "name": "Discover",
            "messageId": "discover-msg-1",
            "payloadVersion": "3",
        },
        "payload": {"scope": {"type": "BearerToken", "token": "discovery-token"}},
    }
}

POWER_CONTROL_EVENT = {
    "directive": {
        "header": {
            "namespace": "Alexa.PowerController",
            "name": "TurnOn",
            "messageId": "power-msg-1",
            "payloadVersion": "3",
        },
        "endpoint": {
            "endpointId": "media_player.tv",
            "scope": {"type": "BearerToken", "token": "endpoint-token"},
        },
        "payload": {},
    }
}


@pytest.fixture(autouse=True)
def base_url_env(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://domus.ardua.com")


def _mock_response(status: int, body: dict):
    mock_resp = mock.MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(body).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_extracts_token_from_payload_scope_for_discovery():
    token = lambda_function._extract_token(DISCOVERY_EVENT)
    assert token == "discovery-token"


def test_extracts_token_from_endpoint_scope_for_power_control():
    token = lambda_function._extract_token(POWER_CONTROL_EVENT)
    assert token == "endpoint-token"


def test_missing_token_returns_invalid_authorization_error():
    event = {"directive": {"header": {"messageId": "x"}, "payload": {}}}
    result = lambda_function.lambda_handler(event, None)
    assert result["event"]["header"]["name"] == "ErrorResponse"
    assert result["event"]["payload"]["type"] == "INVALID_AUTHORIZATION_CREDENTIAL"


def test_missing_base_url_returns_internal_error(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)
    assert result["event"]["payload"]["type"] == "INTERNAL_ERROR"


def test_successful_directive_forwards_and_returns_ha_response():
    ha_response = {
        "event": {
            "header": {"namespace": "Alexa", "name": "Response", "messageId": "power-msg-1"},
            "endpoint": {"endpointId": "media_player.tv"},
            "payload": {},
        }
    }
    with mock.patch("urllib.request.urlopen", return_value=_mock_response(200, ha_response)) as mock_urlopen:
        result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)

    assert result == ha_response
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://domus.ardua.com/api/alexa/smart_home"
    assert request.get_header("Authorization") == "Bearer endpoint-token"
    sent_body = json.loads(request.data.decode("utf-8"))
    assert sent_body == POWER_CONTROL_EVENT


def test_ha_401_maps_to_invalid_authorization_error():
    http_error = urllib.error.HTTPError(
        url="https://domus.ardua.com/api/alexa/smart_home",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=mock.MagicMock(read=lambda: b"unauthorized"),
    )
    with mock.patch("urllib.request.urlopen", side_effect=http_error):
        result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)

    assert result["event"]["payload"]["type"] == "INVALID_AUTHORIZATION_CREDENTIAL"


def test_ha_500_maps_to_internal_error():
    http_error = urllib.error.HTTPError(
        url="https://domus.ardua.com/api/alexa/smart_home",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=mock.MagicMock(read=lambda: b"boom"),
    )
    with mock.patch("urllib.request.urlopen", side_effect=http_error):
        result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)

    assert result["event"]["payload"]["type"] == "INTERNAL_ERROR"


def test_unreachable_ha_maps_to_internal_error():
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)

    assert result["event"]["payload"]["type"] == "INTERNAL_ERROR"


def test_malformed_ha_response_maps_to_internal_error():
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"not json"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        result = lambda_function.lambda_handler(POWER_CONTROL_EVENT, None)

    assert result["event"]["payload"]["type"] == "INTERNAL_ERROR"
