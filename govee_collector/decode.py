"""Govee H5075 BLE advertisement decoding.

Ported from the working prototype (~jramsey/scan.py on mrteeny). The H5075
packs temperature and humidity into a single 3-byte big-endian integer
inside Govee's manufacturer-data payload: dividing by 1000 gives tenths of a
degree C, the remainder gives tenths of a percent RH. Byte 4 is battery
percent. This encoding is undocumented by Govee but well-established from
community reverse-engineering and confirmed live against these exact
sensors.
"""

from __future__ import annotations

from typing import NamedTuple

# BLE MAC address -> logical sensor id.
SENSORS: dict[str, str] = {
    "A4:C1:38:CC:28:47": "TH01",
    "A4:C1:38:7C:DB:27": "TH02",
    "A4:C1:38:5F:C9:FF": "TH03",
}

GOVEE_MANUFACTURER_ID = 60552

# Sensor id -> human-facing location label, shared by MQTT discovery
# (device names) and the dashboard.
DEVICE_LABELS: dict[str, str] = {
    "TH01": "Wineador",
    "TH02": "Drybox",
    "TH03": "Desk",
}


class DecodedReading(NamedTuple):
    temp_f: float
    humidity_pct: float
    battery_pct: int


def decode_h5075(payload: bytes) -> DecodedReading | None:
    """Decode a Govee H5075 manufacturer-data payload.

    Returns None for a payload too short to contain a real reading, rather
    than raising -- a truncated/corrupt advertisement should be silently
    skipped by the caller, not crash the scanner.
    """
    if len(payload) < 5:
        return None

    value = int.from_bytes(payload[1:4], byteorder="big")

    temperature_c = (value // 1000) / 10.0
    humidity_pct = (value % 1000) / 10.0
    battery_pct = payload[4]

    temperature_f = temperature_c * 9 / 5 + 32

    return DecodedReading(temperature_f, humidity_pct, battery_pct)
