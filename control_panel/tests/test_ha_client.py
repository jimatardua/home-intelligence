"""Tests for ha_client.py -- the only thing in this project that talks to
Home Assistant's write API. Mocks `requests` entirely; no live calls,
no real token needed. Focused on the two failure modes that actually
matter for the page (see ha_client.py's docstring): HA unreachable vs.
HA reachable but erroring.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

os.environ.setdefault("HA_TOKEN", "test-token")

from control_panel import ha_client  # noqa: E402


def _ok_response(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = json_body
    return resp


def _error_response(status: int, text: str = "boom") -> MagicMock:
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status
    resp.text = text
    return resp


def test_get_state_returns_parsed_json():
    with patch.object(requests, "get", return_value=_ok_response({"state": "cool"})) as mock_get:
        result = ha_client.get_state("climate.family_room_family_room")

    assert result == {"state": "cool"}
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith("/api/states/climate.family_room_family_room")
    assert mock_get.call_args[1]["headers"]["Authorization"] == "Bearer test-token"


def test_get_state_raises_unreachable_on_connection_error():
    with patch.object(requests, "get", side_effect=requests.ConnectionError("no route")):
        with pytest.raises(ha_client.HomeAssistantUnreachable):
            ha_client.get_state("climate.family_room_family_room")


def test_get_state_raises_ha_error_on_non_ok_response():
    with patch.object(requests, "get", return_value=_error_response(404, "not found")):
        with pytest.raises(ha_client.HomeAssistantError):
            ha_client.get_state("climate.nonexistent")


def test_call_service_posts_correct_url_and_payload():
    with patch.object(requests, "post", return_value=_ok_response([])) as mock_post:
        ha_client.call_service("climate", "set_hvac_mode", "climate.family_room_family_room", hvac_mode="cool")

    called_url = mock_post.call_args[0][0]
    assert called_url.endswith("/api/services/climate/set_hvac_mode")
    payload = mock_post.call_args[1]["json"]
    assert payload == {"entity_id": "climate.family_room_family_room", "hvac_mode": "cool"}


def test_call_service_accepts_a_list_of_entities():
    # Room-level blind commands target all of a room's covers in one call.
    with patch.object(requests, "post", return_value=_ok_response([])) as mock_post:
        ha_client.call_service("cover", "open_cover", ["cover.office_1", "cover.office_2"])

    payload = mock_post.call_args[1]["json"]
    assert payload["entity_id"] == ["cover.office_1", "cover.office_2"]


def test_call_service_raises_unreachable_on_timeout():
    with patch.object(requests, "post", side_effect=requests.Timeout("timed out")):
        with pytest.raises(ha_client.HomeAssistantUnreachable):
            ha_client.call_service("cover", "open_cover", "cover.office_1")


def test_call_service_raises_ha_error_on_non_ok_response():
    # e.g. the blind hub timing out -- HA itself is reachable, it just
    # couldn't complete the request. Confirmed live, see docs/control-panel.md.
    with patch.object(requests, "post", return_value=_error_response(500, "hub timeout")):
        with pytest.raises(ha_client.HomeAssistantError):
            ha_client.call_service("cover", "open_cover", "cover.office_1")


def test_token_missing_raises_clear_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="HA_TOKEN"):
            ha_client.get_state("climate.family_room_family_room")
