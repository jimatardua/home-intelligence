"""Tests for server.py -- Flask routes, with ha_client entirely mocked
(no real HTTP, no real token needed). Focused on: correct entity/service
per button (especially the open_cover/close_cover-vs-set_cover_position
split confirmed live, see const.py's docstring), input validation, and
that both of ha_client's failure modes surface as distinct, non-500
responses rather than a bare server error.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("HA_TOKEN", "test-token")

from control_panel import ha_client, server  # noqa: E402
from control_panel.const import CLIMATE_ENTITY, DINING_COVERS, OFFICE_COVERS  # noqa: E402


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


# --- GET /control/api/thermostat -----------------------------------------


def test_get_thermostat_returns_mode_and_temps(client):
    state = {"state": "cool", "attributes": {"current_temperature": 75, "temperature": 77}}
    with patch.object(ha_client, "get_state", return_value=state):
        resp = client.get("/control/api/thermostat")

    assert resp.status_code == 200
    assert resp.get_json() == {"mode": "cool", "current_temp": 75, "target_temp": 77}


def test_get_thermostat_reads_the_confirmed_entity_id(client):
    with patch.object(ha_client, "get_state", return_value={"state": "off", "attributes": {}}) as mock_get:
        client.get("/control/api/thermostat")

    mock_get.assert_called_once_with(CLIMATE_ENTITY)


def test_get_thermostat_unreachable_returns_503(client):
    with patch.object(ha_client, "get_state", side_effect=ha_client.HomeAssistantUnreachable("no route")):
        resp = client.get("/control/api/thermostat")

    assert resp.status_code == 503
    assert resp.get_json()["error"] == "unreachable"


def test_get_thermostat_ha_error_returns_502(client):
    with patch.object(ha_client, "get_state", side_effect=ha_client.HomeAssistantError("HTTP 404")):
        resp = client.get("/control/api/thermostat")

    assert resp.status_code == 502
    assert resp.get_json()["error"] == "ha_error"


# --- POST /control/api/thermostat -----------------------------------------


def test_set_thermostat_mode_calls_correct_service(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"mode": "heat"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    mock_call.assert_called_once_with("climate", "set_hvac_mode", CLIMATE_ENTITY, hvac_mode="heat")


def test_set_thermostat_mode_rejects_heat_cool(client):
    # Deliberately unsupported -- see const.py's HVAC_MODES docstring.
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"mode": "heat_cool"})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_thermostat_rejects_neither_mode_nor_temperature(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_thermostat_mode_ha_unreachable_returns_503(client):
    with patch.object(ha_client, "call_service", side_effect=ha_client.HomeAssistantUnreachable("x")):
        resp = client.post("/control/api/thermostat", json={"mode": "cool"})

    assert resp.status_code == 503


def test_set_thermostat_temperature_calls_set_temperature(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"temperature": 72})

    assert resp.status_code == 200
    mock_call.assert_called_once_with("climate", "set_temperature", CLIMATE_ENTITY, temperature=72)


def test_set_thermostat_temperature_rejects_out_of_range(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"temperature": 200})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_thermostat_temperature_rejects_non_numeric(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"temperature": "warm"})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_thermostat_temperature_rejects_bool_masquerading_as_number(client):
    # bool is a subclass of int in Python -- isinstance(True, (int, float))
    # is True, so this needs an explicit guard, not just an isinstance check.
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"temperature": True})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_thermostat_accepts_mode_and_temperature_together(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/thermostat", json={"mode": "cool", "temperature": 70})

    assert resp.status_code == 200
    assert mock_call.call_count == 2


# --- POST /control/api/blinds/<room> --------------------------------------


def test_set_blinds_open_uses_open_cover_not_set_position(client):
    # Confirmed live: set_cover_position silently no-ops on repeated calls,
    # open_cover/close_cover don't have that problem. See const.py.
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/blinds/office", json={"position": 100})

    assert resp.status_code == 200
    mock_call.assert_called_once_with("cover", "open_cover", OFFICE_COVERS)


def test_set_blinds_close_uses_close_cover(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/blinds/dining", json={"position": 0})

    assert resp.status_code == 200
    mock_call.assert_called_once_with("cover", "close_cover", DINING_COVERS)


def test_set_blinds_mid_uses_set_cover_position(client):
    # The one case with no dedicated service to fall back on.
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/blinds/office", json={"position": 50})

    assert resp.status_code == 200
    mock_call.assert_called_once_with("cover", "set_cover_position", OFFICE_COVERS, position=50)


def test_set_blinds_targets_all_of_a_rooms_covers_in_one_call(client):
    with patch.object(ha_client, "call_service") as mock_call:
        client.post("/control/api/blinds/dining", json={"position": 100})

    entities_arg = mock_call.call_args[0][2]
    assert entities_arg == DINING_COVERS
    assert len(entities_arg) == 3


def test_set_blinds_rejects_unknown_room(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/blinds/living_room", json={"position": 100})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_blinds_rejects_invalid_position(client):
    with patch.object(ha_client, "call_service") as mock_call:
        resp = client.post("/control/api/blinds/office", json={"position": 37})

    assert resp.status_code == 400
    mock_call.assert_not_called()


def test_set_blinds_ha_error_returns_502(client):
    with patch.object(ha_client, "call_service", side_effect=ha_client.HomeAssistantError("hub timeout")):
        resp = client.post("/control/api/blinds/office", json={"position": 100})

    assert resp.status_code == 502
    assert resp.get_json()["error"] == "ha_error"
