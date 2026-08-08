from __future__ import annotations

import json

import pytest

from govee_collector.collector import (
    HEALTH_STATUS_OK,
    HEALTH_STATUS_STALE,
    HEALTH_STATUS_STUCK,
    RESTART_RETRY_INTERVAL_SECONDS,
    STALE_RESTART_THRESHOLD_SECONDS,
    STUCK_AFTER_CONSECUTIVE_FAILURES,
    DeviceState,
    apply_advertisement,
    build_health_payload,
    build_state_payload,
    compute_health_status,
    is_stale,
    should_attempt_restart,
)
from govee_collector.decode import GOVEE_MANUFACTURER_ID


def _payload_bytes(temp_c: float, humidity_pct: float, battery_pct: int) -> bytes:
    value = round(temp_c * 10) * 1000 + round(humidity_pct * 10)
    return bytes([0]) + value.to_bytes(3, byteorder="big") + bytes([battery_pct])


def test_apply_advertisement_adds_known_device():
    manufacturer_data = {GOVEE_MANUFACTURER_ID: _payload_bytes(21.0, 60.0, 90)}

    state = apply_advertisement({}, "A4:C1:38:CC:28:47", manufacturer_data, rssi=-55, now=1000.0)

    assert "TH01" in state
    assert state["TH01"].temp_f == pytest.approx(21.0 * 9 / 5 + 32)
    assert state["TH01"].humidity_pct == pytest.approx(60.0)
    assert state["TH01"].battery_pct == 90
    assert state["TH01"].rssi == -55
    assert state["TH01"].last_seen == 1000.0


def test_apply_advertisement_is_case_insensitive_on_mac():
    manufacturer_data = {GOVEE_MANUFACTURER_ID: _payload_bytes(21.0, 60.0, 90)}

    state = apply_advertisement({}, "a4:c1:38:cc:28:47", manufacturer_data, rssi=-55)

    assert "TH01" in state


def test_apply_advertisement_ignores_unknown_mac():
    manufacturer_data = {GOVEE_MANUFACTURER_ID: _payload_bytes(21.0, 60.0, 90)}

    state = apply_advertisement({}, "AA:BB:CC:DD:EE:FF", manufacturer_data, rssi=-55)

    assert state == {}


def test_apply_advertisement_ignores_missing_govee_manufacturer_data():
    state = apply_advertisement({}, "A4:C1:38:CC:28:47", {12345: b"\x01\x02\x03\x04\x05"}, rssi=-55)

    assert state == {}


def test_apply_advertisement_ignores_corrupt_short_payload():
    manufacturer_data = {GOVEE_MANUFACTURER_ID: b"\x00\x01"}

    state = apply_advertisement({}, "A4:C1:38:CC:28:47", manufacturer_data, rssi=-55)

    assert state == {}


def test_apply_advertisement_updates_existing_device_without_touching_others():
    manufacturer_data_1 = {GOVEE_MANUFACTURER_ID: _payload_bytes(21.0, 60.0, 90)}
    state = apply_advertisement({}, "A4:C1:38:CC:28:47", manufacturer_data_1, rssi=-55, now=1000.0)

    manufacturer_data_2 = {GOVEE_MANUFACTURER_ID: _payload_bytes(22.0, 61.0, 89)}
    state = apply_advertisement(state, "A4:C1:38:7C:DB:27", manufacturer_data_2, rssi=-70, now=1001.0)

    assert set(state) == {"TH01", "TH02"}
    assert state["TH01"].temp_f == pytest.approx(21.0 * 9 / 5 + 32)
    assert state["TH02"].temp_f == pytest.approx(22.0 * 9 / 5 + 32)


def test_apply_advertisement_returns_new_dict_not_mutated_original():
    original: dict = {}
    manufacturer_data = {GOVEE_MANUFACTURER_ID: _payload_bytes(21.0, 60.0, 90)}

    updated = apply_advertisement(original, "A4:C1:38:CC:28:47", manufacturer_data, rssi=-55)

    assert original == {}
    assert updated != original


def test_build_state_payload_shape_and_rounding():
    state = DeviceState(temp_f=68.876, humidity_pct=65.234, battery_pct=92, rssi=-61, last_seen=0.0)

    payload = json.loads(build_state_payload(state))

    assert payload == {"temp_f": 68.9, "humidity_pct": 65.2, "battery_pct": 92, "rssi": -61}


def test_is_stale_false_when_advertisement_recent():
    now = 1000.0
    assert is_stale(last_advertisement_at=now - 10, now=now) is False


def test_is_stale_false_exactly_at_threshold():
    now = 1000.0
    assert is_stale(last_advertisement_at=now - STALE_RESTART_THRESHOLD_SECONDS, now=now) is False


def test_is_stale_true_past_threshold():
    now = 1000.0
    assert is_stale(last_advertisement_at=now - STALE_RESTART_THRESHOLD_SECONDS - 1, now=now) is True


def test_should_attempt_restart_true_when_stale_and_no_recent_restart():
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 1
    last_restart_attempt_at = 0.0  # never attempted

    assert should_attempt_restart(last_advertisement_at, last_restart_attempt_at, now) is True


def test_should_attempt_restart_false_when_not_stale():
    now = 1000.0
    last_advertisement_at = now - 5  # fresh
    last_restart_attempt_at = 0.0

    assert should_attempt_restart(last_advertisement_at, last_restart_attempt_at, now) is False


def test_should_attempt_restart_false_during_cooldown():
    # Stale, but a restart was just attempted -- must not hammer BlueZ every
    # flush cycle if the underlying adapter state is genuinely stuck.
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 1
    last_restart_attempt_at = now - (RESTART_RETRY_INTERVAL_SECONDS - 1)

    assert should_attempt_restart(last_advertisement_at, last_restart_attempt_at, now) is False


def test_should_attempt_restart_true_after_cooldown_elapses():
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 1
    last_restart_attempt_at = now - (RESTART_RETRY_INTERVAL_SECONDS + 1)

    assert should_attempt_restart(last_advertisement_at, last_restart_attempt_at, now) is True


def test_compute_health_status_ok_when_fresh():
    now = 1000.0
    assert compute_health_status(last_advertisement_at=now - 5, consecutive_restart_failures=0, now=now) == HEALTH_STATUS_OK


def test_compute_health_status_stale_when_gap_but_still_retrying():
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 1
    failures = STUCK_AFTER_CONSECUTIVE_FAILURES - 1

    status = compute_health_status(last_advertisement_at, failures, now)

    assert status == HEALTH_STATUS_STALE


def test_compute_health_status_stuck_after_enough_consecutive_failures():
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 1

    status = compute_health_status(last_advertisement_at, STUCK_AFTER_CONSECUTIVE_FAILURES, now)

    assert status == HEALTH_STATUS_STUCK


def test_compute_health_status_ok_even_with_stale_failure_count_if_advertisement_is_fresh():
    # A high failure count from a past incident shouldn't linger and cause
    # a false "stuck" reading once real data is flowing again -- callers
    # (run()) are expected to reset the failure counter on a real
    # advertisement, but compute_health_status() itself is also correctly
    # OK-first regardless, since staleness is the primary signal.
    now = 1000.0
    status = compute_health_status(last_advertisement_at=now - 1, consecutive_restart_failures=10, now=now)

    assert status == HEALTH_STATUS_OK


def test_build_health_payload_shape_when_fresh():
    now = 1000.0
    last_advertisement_at = now - 5  # well under STALE_RESTART_THRESHOLD_SECONDS

    payload = json.loads(build_health_payload(last_advertisement_at, consecutive_restart_failures=0, now=now))

    assert payload == {
        "status": HEALTH_STATUS_OK,
        "seconds_since_last_advertisement": 5,
        "consecutive_restart_failures": 0,
    }


def test_build_health_payload_shape_when_stuck():
    now = 1000.0
    last_advertisement_at = now - STALE_RESTART_THRESHOLD_SECONDS - 42

    payload = json.loads(
        build_health_payload(last_advertisement_at, consecutive_restart_failures=STUCK_AFTER_CONSECUTIVE_FAILURES, now=now)
    )

    assert payload == {
        "status": HEALTH_STATUS_STUCK,
        "seconds_since_last_advertisement": round(STALE_RESTART_THRESHOLD_SECONDS + 42),
        "consecutive_restart_failures": STUCK_AFTER_CONSECUTIVE_FAILURES,
    }
