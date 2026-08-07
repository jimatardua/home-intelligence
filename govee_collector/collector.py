"""BLE scanning + MQTT publish for the Govee H5075 cigar-storage sensors.

Decouples the BLE advertisement rate (a callback fires every few seconds per
device) from MQTT publish rate: advertisements only update in-memory state;
a periodic flush publishes it. 3 devices chattering independently doesn't
turn into 3x the broker traffic it needs to, and the flush interval stays
far inside the 5-minute `expire_after` staleness window (discovery.py).

Requires environment variables MQTT_HOST, MQTT_USERNAME, MQTT_PASSWORD (the
systemd unit supplies these, the password via a non-repo env file -- see
deploy.sh).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from bleak import BleakScanner

from govee_collector.decode import GOVEE_MANUFACTURER_ID, SENSORS, decode_h5075
from govee_collector.discovery import (
    STATUS_PAYLOAD_AVAILABLE,
    STATUS_PAYLOAD_NOT_AVAILABLE,
    STATUS_TOPIC,
    all_discovery_messages,
    state_topic,
)

LOGGER = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 15.0
MQTT_PORT = 1883
MQTT_KEEPALIVE_SECONDS = 60


@dataclass(frozen=True)
class DeviceState:
    temp_f: float
    humidity_pct: float
    battery_pct: int
    rssi: int
    last_seen: float  # time.time() -- logging/debugging only, not published


def apply_advertisement(
    state: dict[str, DeviceState],
    mac: str,
    manufacturer_data: dict[int, bytes],
    rssi: int,
    now: float | None = None,
) -> dict[str, DeviceState]:
    """Pure state-update step.

    Given the current per-device state plus one BLE advertisement's raw
    fields, returns the updated state dict (a new dict, not mutated in
    place). Kept separate from the actual bleak callback specifically so
    it's unit-testable without any BLE hardware or the bleak library at all.
    Advertisements from unknown MACs, missing Govee manufacturer data, or a
    too-short/corrupt payload are silently ignored -- the caller doesn't
    need to distinguish "not a Govee sensor" from "not one of ours" from
    "garbled packet," all three just mean "no update this time."
    """
    device_id = SENSORS.get(mac.upper())
    if device_id is None:
        return state

    payload = manufacturer_data.get(GOVEE_MANUFACTURER_ID)
    if payload is None:
        return state

    decoded = decode_h5075(payload)
    if decoded is None:
        return state

    new_state = dict(state)
    new_state[device_id] = DeviceState(
        temp_f=decoded.temp_f,
        humidity_pct=decoded.humidity_pct,
        battery_pct=decoded.battery_pct,
        rssi=rssi,
        last_seen=now if now is not None else time.time(),
    )
    return new_state


def build_state_payload(device_state: DeviceState) -> str:
    return json.dumps(
        {
            "temp_f": round(device_state.temp_f, 1),
            "humidity_pct": round(device_state.humidity_pct, 1),
            "battery_pct": device_state.battery_pct,
            "rssi": device_state.rssi,
        }
    )


def _publish_discovery(client: mqtt.Client) -> None:
    for topic, payload in all_discovery_messages():
        client.publish(topic, json.dumps(payload), qos=1, retain=True)


def _build_client() -> mqtt.Client:
    host = os.environ["MQTT_HOST"]
    username = os.environ["MQTT_USERNAME"]
    password = os.environ["MQTT_PASSWORD"]

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="govee-collector")
    client.username_pw_set(username, password)
    # LWT: if this process dies or the connection drops, the broker itself
    # flips the status topic to "offline" -- a faster, connection-level
    # health signal than waiting for every entity's expire_after to lapse.
    client.will_set(STATUS_TOPIC, payload=STATUS_PAYLOAD_NOT_AVAILABLE, qos=1, retain=True)

    def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            LOGGER.error("MQTT connect failed: %s", reason_code)
            return
        LOGGER.info("Connected to MQTT broker -- publishing discovery config")
        _publish_discovery(client)
        client.publish(STATUS_TOPIC, payload=STATUS_PAYLOAD_AVAILABLE, qos=1, retain=True)

    client.on_connect = on_connect
    client.connect(host, MQTT_PORT, keepalive=MQTT_KEEPALIVE_SECONDS)
    client.loop_start()
    return client


async def run() -> None:
    state: dict[str, DeviceState] = {}
    client = _build_client()

    def callback(device, adv) -> None:
        nonlocal state
        state = apply_advertisement(state, device.address, adv.manufacturer_data, adv.rssi)

    scanner = BleakScanner(callback)
    await scanner.start()
    LOGGER.info("Scanning for Govee sensors...")

    try:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            for device_id, device_state in state.items():
                client.publish(state_topic(device_id), build_state_payload(device_state), qos=1, retain=True)
                LOGGER.debug("Published %s: %s", device_id, device_state)
    finally:
        await scanner.stop()
        client.publish(STATUS_TOPIC, payload=STATUS_PAYLOAD_NOT_AVAILABLE, qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
