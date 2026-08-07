from __future__ import annotations

import pytest

from govee_collector.decode import decode_h5075


def _encode_payload(temp_c: float, humidity_pct: float, battery_pct: int, flag_byte: int = 0) -> bytes:
    """Build a synthetic H5075 manufacturer-data payload from known values,
    the inverse of decode_h5075 -- lets tests assert round-trip correctness
    against real physical quantities instead of hand-picked magic bytes."""
    value = round(temp_c * 10) * 1000 + round(humidity_pct * 10)
    return bytes([flag_byte]) + value.to_bytes(3, byteorder="big") + bytes([battery_pct])


def test_decode_typical_reading():
    payload = _encode_payload(temp_c=21.5, humidity_pct=65.2, battery_pct=92)

    decoded = decode_h5075(payload)

    assert decoded is not None
    assert decoded.temp_f == pytest.approx(21.5 * 9 / 5 + 32)
    assert decoded.humidity_pct == pytest.approx(65.2)
    assert decoded.battery_pct == 92


def test_decode_zero_values():
    payload = _encode_payload(temp_c=0.0, humidity_pct=0.0, battery_pct=0)

    decoded = decode_h5075(payload)

    assert decoded is not None
    assert decoded.temp_f == pytest.approx(32.0)
    assert decoded.humidity_pct == pytest.approx(0.0)
    assert decoded.battery_pct == 0


def test_decode_full_battery_and_high_humidity():
    payload = _encode_payload(temp_c=35.0, humidity_pct=99.9, battery_pct=100)

    decoded = decode_h5075(payload)

    assert decoded is not None
    assert decoded.temp_f == pytest.approx(35.0 * 9 / 5 + 32)
    assert decoded.humidity_pct == pytest.approx(99.9)
    assert decoded.battery_pct == 100


def test_decode_too_short_payload_returns_none():
    assert decode_h5075(b"\x00\x01\x02\x03") is None


def test_decode_empty_payload_returns_none():
    assert decode_h5075(b"") is None


def test_decode_minimum_valid_length():
    # Exactly 5 bytes is the shortest a real payload can be.
    payload = _encode_payload(temp_c=20.0, humidity_pct=50.0, battery_pct=75)
    assert len(payload) == 5

    decoded = decode_h5075(payload)

    assert decoded is not None
