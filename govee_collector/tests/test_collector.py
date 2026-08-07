from __future__ import annotations

import json

import pytest

from govee_collector.collector import DeviceState, apply_advertisement, build_state_payload
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
