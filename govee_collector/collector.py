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
from dataclasses import dataclass, replace

import paho.mqtt.client as mqtt
from bleak import BleakScanner

from govee_collector.decode import GOVEE_MANUFACTURER_ID, SENSORS, decode_h5075
from govee_collector.discovery import (
    HEALTH_TOPIC,
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

# Found live (2026-08-08): BLE advertisement delivery can silently stop
# while the process itself keeps running and stays MQTT-connected -- no
# exception, no crash, just no more callbacks. Most likely cause: a second
# process independently scanning the same adapter (BlueZ has no clean
# multi-client discovery story; observed symptom on the *next* restart
# attempt was `org.bluez.Error.InProgress`, the classic contention error).
# Went undetected for ~8 hours because nothing was watching for it -- this
# threshold is deliberately far inside the 5-minute HA `expire_after`
# (discovery.py) so a stall self-heals before HA ever marks anything
# unavailable, rather than relying on a human noticing stale numbers.
STALE_RESTART_THRESHOLD_SECONDS = 180.0

# Restarting the BLE scan session is itself not guaranteed to succeed if
# BlueZ's adapter-level discovery state is stuck (that InProgress error
# above) -- this cooldown stops the watchdog from hammering a stuck adapter
# every FLUSH_INTERVAL_SECONDS; systemd's Restart=always remains the final
# fallback if restarts keep failing indefinitely.
RESTART_RETRY_INTERVAL_SECONDS = 60.0

# 3 failed restart attempts in a row (>= ~3 minutes of retrying, on top of
# the 3 minutes it took to detect the stall in the first place) means the
# watchdog isn't going to fix this on its own -- almost certainly BlueZ's
# adapter-level discovery state is stuck, which needs a real reset (`hciconfig hci0 down`/`up` + `systemctl restart
# bluetooth`) the collector deliberately doesn't have the privileges to do
# itself. This is exactly the distinction the "Problem"/"Status" HA
# entities (discovery.py) exist to surface -- see docs/govee-cigar-monitor.md.
#
# "Failed" here means "did not produce an advertisement," NOT "raised an
# exception": run() increments this on every restart attempt and only the
# advertisement callback clears it. Both known lockup classes are covered
# that way -- the noisy one (org.bluez.Error.InProgress on start) and the
# silent one found 2026-09-09, where every BlueZ call succeeds and no
# advertisement is ever delivered.
STUCK_AFTER_CONSECUTIVE_FAILURES = 3

HEALTH_STATUS_OK = "ok"
HEALTH_STATUS_STALE = "stale"
HEALTH_STATUS_STUCK = "stuck"


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


def is_stale(last_advertisement_at: float, now: float) -> bool:
    return (now - last_advertisement_at) > STALE_RESTART_THRESHOLD_SECONDS


def should_attempt_restart(last_advertisement_at: float, last_restart_attempt_at: float, now: float) -> bool:
    """Pure decision logic, unit-testable without asyncio/bleak: stale AND
    not still cooling down from a recent restart attempt."""
    return is_stale(last_advertisement_at, now) and (now - last_restart_attempt_at) > RESTART_RETRY_INTERVAL_SECONDS


@dataclass(frozen=True)
class WatchdogState:
    """The stall watchdog's bookkeeping, as one immutable value.

    Exists because the 2026-09-09 blind-collector incident lived entirely
    in run()'s loose local variables -- the one part of this module with no
    unit tests, precisely because it was tangled up with asyncio and bleak.
    Modelling the bookkeeping as pure transitions over a single value (the
    same approach apply_advertisement() already takes for device state)
    makes both known BLE failure modes testable with no hardware at all.
    """

    last_advertisement_at: float
    last_restart_attempt_at: float = 0.0
    consecutive_restart_failures: int = 0


def after_advertisement(watchdog: WatchdogState, now: float) -> WatchdogState:
    """A real Govee decode just arrived -- the staleness clock resets and
    the failure count clears. An advertisement is the *only* evidence that
    the scan session actually works, which is why this is the only place
    either of those two things happens."""
    return replace(watchdog, last_advertisement_at=now, consecutive_restart_failures=0)


def after_restart_attempt(watchdog: WatchdogState, now: float) -> WatchdogState:
    """A restart of the scan session was just attempted, whether or not the
    BlueZ calls appeared to succeed.

    Deliberately does NOT advance last_advertisement_at, and counts the
    attempt as a failure until an advertisement proves otherwise. The
    earlier version did the opposite -- treating a non-raising
    `scanner.start()` as success and resetting the staleness clock -- which
    is exactly what made the 2026-09-09 kernel-level HCI lockup invisible:
    every BlueZ call succeeded while zero advertisements were delivered, so
    health published "ok" for 13 hours and nothing ever escalated.
    """
    return replace(
        watchdog,
        last_restart_attempt_at=now,
        consecutive_restart_failures=watchdog.consecutive_restart_failures + 1,
    )


def compute_health_status(last_advertisement_at: float, consecutive_restart_failures: int, now: float) -> str:
    """"ok" while advertisements are arriving normally; "stale" once the
    watchdog notices a gap but is still within its retry budget; "stuck"
    once retries have been exhausted and a human needs to intervene (see
    STUCK_AFTER_CONSECUTIVE_FAILURES)."""
    if not is_stale(last_advertisement_at, now):
        return HEALTH_STATUS_OK
    if consecutive_restart_failures >= STUCK_AFTER_CONSECUTIVE_FAILURES:
        return HEALTH_STATUS_STUCK
    return HEALTH_STATUS_STALE


def build_health_payload(last_advertisement_at: float, consecutive_restart_failures: int, now: float) -> str:
    return json.dumps(
        {
            "status": compute_health_status(last_advertisement_at, consecutive_restart_failures, now),
            "seconds_since_last_advertisement": round(now - last_advertisement_at),
            "consecutive_restart_failures": consecutive_restart_failures,
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
    watchdog = WatchdogState(last_advertisement_at=time.time())

    def callback(device, adv) -> None:
        nonlocal state, watchdog
        updated = apply_advertisement(state, device.address, adv.manufacturer_data, adv.rssi)
        if updated is not state:  # a real Govee decode, not just BLE noise from other devices
            watchdog = after_advertisement(watchdog, time.time())
        state = updated

    scanner = BleakScanner(callback)
    await scanner.start()
    LOGGER.info("Scanning for Govee sensors...")

    try:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            now = time.time()

            if should_attempt_restart(watchdog.last_advertisement_at, watchdog.last_restart_attempt_at, now):
                LOGGER.warning(
                    "No Govee advertisement in %.0fs -- restarting the BLE scan session",
                    now - watchdog.last_advertisement_at,
                )
                # Bookkeeping happens BEFORE the attempt, and counts it as a
                # failure until an advertisement proves otherwise -- see
                # after_restart_attempt() for why (2026-09-09 incident).
                watchdog = after_restart_attempt(watchdog, now)
                try:
                    await scanner.stop()
                except Exception:
                    LOGGER.exception("Error stopping the stalled scanner (continuing anyway)")
                try:
                    scanner = BleakScanner(callback)
                    await scanner.start()
                    LOGGER.info(
                        "BLE scan session restarted (%d restart(s) so far with no advertisement since)",
                        watchdog.consecutive_restart_failures,
                    )
                except Exception:
                    # Most likely BlueZ's adapter-level discovery state is
                    # itself stuck (org.bluez.Error.InProgress) -- a plain
                    # scanner restart can't fix that on its own. Don't
                    # crash: log and let the next watchdog check retry,
                    # with systemd's Restart=always as the final fallback
                    # if this process ever exits some other way.
                    LOGGER.exception(
                        "Failed to restart the BLE scan session (%d consecutive failures) -- will retry",
                        watchdog.consecutive_restart_failures,
                    )

            health_status = compute_health_status(
                watchdog.last_advertisement_at, watchdog.consecutive_restart_failures, now
            )
            if health_status != HEALTH_STATUS_OK:
                LOGGER.warning("Collector health: %s", health_status)
            client.publish(
                HEALTH_TOPIC,
                build_health_payload(
                    watchdog.last_advertisement_at, watchdog.consecutive_restart_failures, now
                ),
                qos=1,
                retain=True,
            )

            for device_id, device_state in state.items():
                client.publish(state_topic(device_id), build_state_payload(device_state), qos=1, retain=True)
                LOGGER.debug("Published %s: %s", device_id, device_state)
    finally:
        await scanner.stop()
        client.publish(STATUS_TOPIC, payload=STATUS_PAYLOAD_NOT_AVAILABLE, qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
