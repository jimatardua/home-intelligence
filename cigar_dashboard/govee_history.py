"""Current + historical readings for the 3 Govee cigar-storage sensors.

Reads the plain numeric HA sensor entities created by govee_collector's
MQTT-discovery publishes (see docs/govee-cigar-monitor.md) -- no
Govee/MQTT-specific logic here at all, just entity IDs handed to
energy_report.ha_recorder's existing, already-tested readers, the same way
home_dashboard/temp_history.py does for the Eve Weather sensor.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from energy_report.ha_recorder import get_latest_state, get_numeric_sensor_samples

DEVICE_IDS: tuple[str, ...] = ("TH01", "TH02", "TH03")

DEVICE_LABELS: dict[str, str] = {
    "TH01": "Wineador",
    "TH02": "Drybox",
    "TH03": "Desk",
}

# govee_collector/discovery.py sets an explicit `object_id` on every
# MQTT-discovery payload, but HA does not actually use it when a `device`
# block + `has_entity_name: true` are both present (confirmed live) --
# entity IDs are instead generated from the combined device+entity display
# name: "sensor.{label}_{device_id}_{metric}", all lowercased. Verified
# directly against the real entities HA created
# (sensor.wineador_th01_temperature, sensor.desk_th03_signal_strength,
# etc.), not assumed from the discovery payload we publish.


def _entity_id(device_id: str, metric: str) -> str:
    return f"sensor.{DEVICE_LABELS[device_id].lower()}_{device_id.lower()}_{metric}"


# Gap states the recorder can hold that mean "no real value," not
# literally "off"/"0" -- same convention energy_report.ha_recorder uses
# internally, applied here at the raw-string level before this module's
# own True/False interpretation of the "problem" binary_sensor.
_GAP_STATES = frozenset({"unknown", "unavailable", "none", ""})

COLLECTOR_PROBLEM_ENTITY = "binary_sensor.govee_collector_problem"
COLLECTOR_STATUS_ENTITY = "sensor.govee_collector_status"
COLLECTOR_STALE_SECONDS_ENTITY = "sensor.govee_collector_seconds_since_last_reading"


@dataclass(frozen=True)
class DeviceReading:
    label: str
    temp_f: float | None
    humidity_pct: float | None
    battery_pct: float | None


@dataclass(frozen=True)
class CollectorHealth:
    is_problem: bool
    status: str | None  # "ok" / "stale" / "stuck", or None if genuinely unknown
    seconds_since_last_reading: float | None


@dataclass(frozen=True)
class HistoryPoint:
    at_local: datetime
    value: float


def _float_or_none(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def get_current_readings(conn: sqlite3.Connection) -> dict[str, DeviceReading]:
    """Latest temp/humidity/battery for each of the 3 devices.

    A device with no data at all yet (never seen, or HA restarted before its
    first discovery message landed) yields all-None fields rather than being
    omitted -- the dashboard shows "--" for missing fields, the same
    gap-aware convention used everywhere else in this project (never a
    fabricated value for absent data).
    """
    return {
        device_id: DeviceReading(
            label=DEVICE_LABELS[device_id],
            temp_f=_float_or_none(get_latest_state(conn, _entity_id(device_id, "temperature"))),
            humidity_pct=_float_or_none(get_latest_state(conn, _entity_id(device_id, "humidity"))),
            battery_pct=_float_or_none(get_latest_state(conn, _entity_id(device_id, "battery"))),
        )
        for device_id in DEVICE_IDS
    }


def get_collector_health(conn: sqlite3.Connection) -> CollectorHealth:
    """Current health of the govee_collector daemon itself (mrteeny), not
    any one device's reading -- see docs/govee-cigar-monitor.md.

    A gap state (entity missing/unavailable/unknown -- e.g. HA just
    restarted, or the collector's MQTT connection is down entirely, per its
    LWT) is treated as a problem too, not silently ignored: unlike a single
    sensor reading (where "--" is the honest, low-stakes answer for a gap),
    this entity's entire purpose is catching anomalies, so "we can't tell"
    should read as "something to check," not as "everything's fine."
    """
    problem_raw = get_latest_state(conn, COLLECTOR_PROBLEM_ENTITY)
    status_raw = get_latest_state(conn, COLLECTOR_STATUS_ENTITY)
    seconds_raw = get_latest_state(conn, COLLECTOR_STALE_SECONDS_ENTITY)

    problem_is_gap = problem_raw is None or problem_raw.lower() in _GAP_STATES
    status_is_gap = status_raw is None or status_raw.lower() in _GAP_STATES

    return CollectorHealth(
        is_problem=problem_is_gap or problem_raw.lower() == "on",
        status=None if status_is_gap else status_raw,
        seconds_since_last_reading=_float_or_none(seconds_raw),
    )


def _history(conn: sqlite3.Connection, entity_id: str, now_local: datetime, days: int) -> list[HistoryPoint]:
    samples = get_numeric_sensor_samples(conn, entity_id, now_local - timedelta(days=days), now_local)
    return [HistoryPoint(at_local=s.at_local, value=s.value) for s in samples if s.value is not None]


def get_humidity_history(
    conn: sqlite3.Connection, now_local: datetime, days: int = 7
) -> dict[str, list[HistoryPoint]]:
    return {
        device_id: _history(conn, _entity_id(device_id, "humidity"), now_local, days) for device_id in DEVICE_IDS
    }


def get_temp_history(
    conn: sqlite3.Connection, now_local: datetime, days: int = 7
) -> dict[str, list[HistoryPoint]]:
    return {
        device_id: _history(conn, _entity_id(device_id, "temperature"), now_local, days) for device_id in DEVICE_IDS
    }
