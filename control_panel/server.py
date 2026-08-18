"""Flask backend for the control panel -- the only thing that ever holds
`HA_TOKEN` or talks to Home Assistant directly. Binds 127.0.0.1 only;
`ha-proxy` (nginx, --network host) reverse-proxies `/control/api/` to it,
the same way it already proxies to HA itself on 127.0.0.1:8123.

Every route returns a clear JSON error shape on failure rather than a bare
500 -- see ha_client.py's docstring for why HA-unreachable and
HA-returned-an-error are kept distinct.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from control_panel import ha_client
from control_panel.const import (
    CLIMATE_ENTITY,
    COVER_MID_POSITION,
    COVER_POSITION_SERVICE,
    HVAC_MODES,
    ROOM_COVERS,
)

app = Flask(__name__)


def _error_response(err: Exception) -> tuple:
    if isinstance(err, ha_client.HomeAssistantUnreachable):
        return jsonify({"error": "unreachable", "message": str(err)}), 503
    if isinstance(err, ha_client.HomeAssistantError):
        return jsonify({"error": "ha_error", "message": str(err)}), 502
    raise err


@app.route("/control/api/thermostat", methods=["GET"])
def get_thermostat():
    try:
        state = ha_client.get_state(CLIMATE_ENTITY)
    except (ha_client.HomeAssistantUnreachable, ha_client.HomeAssistantError) as err:
        return _error_response(err)
    attrs = state.get("attributes", {})
    return jsonify(
        {
            "mode": state.get("state"),
            "current_temp": attrs.get("current_temperature"),
            "target_temp": attrs.get("temperature"),
        }
    )


@app.route("/control/api/thermostat", methods=["POST"])
def set_thermostat_mode():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    if mode not in HVAC_MODES:
        return jsonify({"error": "invalid_request", "message": f"mode must be one of {HVAC_MODES}"}), 400
    try:
        ha_client.call_service("climate", "set_hvac_mode", CLIMATE_ENTITY, hvac_mode=mode)
    except (ha_client.HomeAssistantUnreachable, ha_client.HomeAssistantError) as err:
        return _error_response(err)
    return jsonify({"ok": True})


@app.route("/control/api/blinds/<room>", methods=["POST"])
def set_blinds_position(room: str):
    entities = ROOM_COVERS.get(room)
    if entities is None:
        return jsonify({"error": "invalid_request", "message": f"unknown room {room!r}"}), 400

    body = request.get_json(silent=True) or {}
    position = body.get("position")
    if position not in (0, 50, 100):
        return jsonify({"error": "invalid_request", "message": "position must be 0, 50, or 100"}), 400

    try:
        if position == COVER_MID_POSITION:
            ha_client.call_service("cover", "set_cover_position", entities, position=position)
        else:
            ha_client.call_service("cover", COVER_POSITION_SERVICE[position], entities)
    except (ha_client.HomeAssistantUnreachable, ha_client.HomeAssistantError) as err:
        return _error_response(err)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765)
