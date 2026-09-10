from __future__ import annotations

import json

import pytest

from govee_collector.collector import (
    FLUSH_INTERVAL_SECONDS,
    HEALTH_STATUS_OK,
    HEALTH_STATUS_STALE,
    HEALTH_STATUS_STUCK,
    RESTART_RETRY_INTERVAL_SECONDS,
    STALE_RESTART_THRESHOLD_SECONDS,
    STUCK_AFTER_CONSECUTIVE_FAILURES,
    DeviceState,
    WatchdogState,
    after_advertisement,
    after_restart_attempt,
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


# --- Watchdog state transitions (2026-09-09 blind-collector regression) ----
#
# The incident these cover: a kernel-level HCI lockup on mrteeny left hci0
# accepting every BlueZ call while delivering zero advertisements. The old
# run() treated a non-raising `scanner.start()` as success and reset the
# staleness clock on every restart, so health published "ok" for 13 hours
# while the collector was completely blind, ble_auto_reset.py never saw a
# "stuck" line to escalate on, and the outage surfaced only as blank
# readings on the dashboard that a human happened to notice.


def test_after_advertisement_resets_clock_and_clears_failures():
    watchdog = WatchdogState(
        last_advertisement_at=500.0, last_restart_attempt_at=900.0, consecutive_restart_failures=7
    )

    updated = after_advertisement(watchdog, now=1000.0)

    assert updated.last_advertisement_at == 1000.0
    assert updated.consecutive_restart_failures == 0
    assert updated.last_restart_attempt_at == 900.0  # untouched


def test_after_restart_attempt_does_not_advance_the_staleness_clock():
    # The heart of the bug: a restart attempt is not evidence of recovery,
    # so it must not make the collector look freshly-fed.
    watchdog = WatchdogState(last_advertisement_at=500.0)

    updated = after_restart_attempt(watchdog, now=1000.0)

    assert updated.last_advertisement_at == 500.0
    assert updated.last_restart_attempt_at == 1000.0
    assert updated.consecutive_restart_failures == 1


def _simulate_flush_loop(watchdog: WatchdogState, start: float, cycles: int, *, advertisements: bool):
    """Drive the same pure decisions run()'s loop makes, one flush at a time.

    `advertisements=False` models the silent lockup (every restart call
    returns cleanly, nothing is ever delivered); True models a working
    adapter that responds to the restart.
    """
    now = start
    statuses = []
    for _ in range(cycles):
        now += FLUSH_INTERVAL_SECONDS
        if should_attempt_restart(watchdog.last_advertisement_at, watchdog.last_restart_attempt_at, now):
            watchdog = after_restart_attempt(watchdog, now)
            if advertisements:
                watchdog = after_advertisement(watchdog, now)
        statuses.append(
            compute_health_status(watchdog.last_advertisement_at, watchdog.consecutive_restart_failures, now)
        )
    return watchdog, statuses, now


def test_silently_blind_adapter_escalates_to_stuck_instead_of_reporting_ok():
    start = 1000.0
    watchdog = WatchdogState(last_advertisement_at=start)

    # 30 minutes of flushes with a cleanly-lying adapter.
    cycles = int((30 * 60) / FLUSH_INTERVAL_SECONDS)
    watchdog, statuses, now = _simulate_flush_loop(watchdog, start, cycles, advertisements=False)

    assert statuses[0] == HEALTH_STATUS_OK  # nothing wrong yet -- inside the stall threshold
    assert HEALTH_STATUS_STALE in statuses  # noticed the gap
    assert statuses[-1] == HEALTH_STATUS_STUCK  # and escalated, rather than settling back to "ok"

    # The specific old behaviour being locked out: once the watchdog has
    # noticed the gap, a restart attempt must never flip health back to
    # "ok" while the adapter is still delivering nothing. (Before the fix
    # this oscillated ok -> stale -> ok -> stale... forever, and "stuck"
    # was unreachable.)
    first_unhealthy = next(i for i, s in enumerate(statuses) if s != HEALTH_STATUS_OK)
    assert HEALTH_STATUS_OK not in statuses[first_unhealthy:]

    # The published number a human (or ble_auto_reset) reads must be the
    # real outage duration, not the time since the last restart attempt.
    payload = json.loads(
        build_health_payload(watchdog.last_advertisement_at, watchdog.consecutive_restart_failures, now)
    )
    assert payload["status"] == HEALTH_STATUS_STUCK
    assert payload["seconds_since_last_advertisement"] >= 30 * 60 - FLUSH_INTERVAL_SECONDS
    assert payload["consecutive_restart_failures"] >= STUCK_AFTER_CONSECUTIVE_FAILURES


def test_stuck_is_reached_promptly_enough_for_ble_auto_reset_to_act():
    # ble_auto_reset.py only acts on a "stuck" line within its 5-minute
    # journal lookback window, so "eventually stuck" isn't good enough.
    start = 1000.0
    watchdog = WatchdogState(last_advertisement_at=start)
    cycles = int((15 * 60) / FLUSH_INTERVAL_SECONDS)

    _, statuses, _ = _simulate_flush_loop(watchdog, start, cycles, advertisements=False)

    assert HEALTH_STATUS_STUCK in statuses


def test_restart_that_actually_works_returns_to_ok_and_clears_failures():
    start = 1000.0
    watchdog = WatchdogState(last_advertisement_at=start, consecutive_restart_failures=2)
    cycles = int((15 * 60) / FLUSH_INTERVAL_SECONDS)

    watchdog, statuses, _ = _simulate_flush_loop(watchdog, start, cycles, advertisements=True)

    assert watchdog.consecutive_restart_failures == 0
    assert statuses[-1] == HEALTH_STATUS_OK
    assert HEALTH_STATUS_STUCK not in statuses
