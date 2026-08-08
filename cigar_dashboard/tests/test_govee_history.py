from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from cigar_dashboard.govee_history import (
    get_collector_health,
    get_current_readings,
    get_humidity_history,
    get_temp_history,
)

LOCAL_TZ = timezone(timedelta(hours=-6))


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
    )
    yield connection
    connection.close()


def _add_entity(connection: sqlite3.Connection, metadata_id: int, entity_id: str) -> None:
    connection.execute("INSERT INTO states_meta VALUES (?, ?)", (metadata_id, entity_id))


def _add_state(connection: sqlite3.Connection, metadata_id: int, state: str, at_local: datetime) -> None:
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (?, ?, ?)",
        (metadata_id, state, at_local.timestamp()),
    )


def test_get_current_readings_all_three_devices(conn):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.wineador_th01_temperature")
    _add_state(conn, 1, "68.5", now)
    _add_entity(conn, 2, "sensor.wineador_th01_humidity")
    _add_state(conn, 2, "65.2", now)
    _add_entity(conn, 3, "sensor.wineador_th01_battery")
    _add_state(conn, 3, "92", now)

    readings = get_current_readings(conn)

    assert readings["TH01"].label == "Wineador"
    assert readings["TH01"].temp_f == pytest.approx(68.5)
    assert readings["TH01"].humidity_pct == pytest.approx(65.2)
    assert readings["TH01"].battery_pct == pytest.approx(92.0)
    # No data at all for TH02/TH03 in this test -- must not fabricate values.
    assert readings["TH02"].temp_f is None
    assert readings["TH02"].humidity_pct is None
    assert readings["TH03"].battery_pct is None


def test_get_current_readings_treats_gap_state_as_none(conn):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.drybox_th02_humidity")
    _add_state(conn, 1, "unavailable", now)

    readings = get_current_readings(conn)

    assert readings["TH02"].humidity_pct is None


def test_get_humidity_history_returns_points_per_device(conn):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.wineador_th01_humidity")
    _add_state(conn, 1, "64.0", now - timedelta(days=2))
    _add_state(conn, 1, "65.5", now - timedelta(days=1))
    # get_numeric_sensor_samples' window is [start, end) -- a sample placed
    # exactly at `now` (the end boundary itself) would be excluded, so the
    # "most recent" sample here sits a minute before it, matching how real
    # data never lands exactly on the query boundary either.
    _add_state(conn, 1, "66.1", now - timedelta(minutes=1))

    history = get_humidity_history(conn, now, days=7)

    assert [p.value for p in history["TH01"]] == pytest.approx([64.0, 65.5, 66.1])
    assert history["TH02"] == []
    assert history["TH03"] == []


def test_get_humidity_history_omits_gap_samples(conn):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.desk_th03_humidity")
    _add_state(conn, 1, "40.0", now - timedelta(hours=2))
    _add_state(conn, 1, "unavailable", now - timedelta(hours=1))
    _add_state(conn, 1, "41.0", now - timedelta(minutes=1))

    history = get_humidity_history(conn, now, days=7)

    assert [p.value for p in history["TH03"]] == pytest.approx([40.0, 41.0])


def test_get_temp_history_respects_days_window(conn):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.wineador_th01_temperature")
    _add_state(conn, 1, "60.0", now - timedelta(days=10))  # outside a 7-day window
    _add_state(conn, 1, "68.0", now - timedelta(days=1))

    history = get_temp_history(conn, now, days=7)

    assert [p.value for p in history["TH01"]] == pytest.approx([68.0])


def test_get_temp_history_less_than_seven_days_of_data_is_not_an_error(conn):
    # Day 1 in production: the collector's only been running a few hours.
    now = datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "sensor.wineador_th01_temperature")
    _add_state(conn, 1, "68.0", now - timedelta(hours=1))

    history = get_temp_history(conn, now, days=7)

    assert [p.value for p in history["TH01"]] == pytest.approx([68.0])


def test_get_collector_health_ok(conn):
    now = datetime(2026, 8, 8, 8, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "binary_sensor.govee_collector_problem")
    _add_state(conn, 1, "off", now)
    _add_entity(conn, 2, "sensor.govee_collector_status")
    _add_state(conn, 2, "ok", now)
    _add_entity(conn, 3, "sensor.govee_collector_seconds_since_last_reading")
    _add_state(conn, 3, "4", now)

    health = get_collector_health(conn)

    assert health.is_problem is False
    assert health.status == "ok"
    assert health.seconds_since_last_reading == pytest.approx(4.0)


def test_get_collector_health_problem_when_binary_sensor_on(conn):
    now = datetime(2026, 8, 8, 8, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "binary_sensor.govee_collector_problem")
    _add_state(conn, 1, "on", now)
    _add_entity(conn, 2, "sensor.govee_collector_status")
    _add_state(conn, 2, "stuck", now)
    _add_entity(conn, 3, "sensor.govee_collector_seconds_since_last_reading")
    _add_state(conn, 3, "612", now)

    health = get_collector_health(conn)

    assert health.is_problem is True
    assert health.status == "stuck"
    assert health.seconds_since_last_reading == pytest.approx(612.0)


def test_get_collector_health_treats_gap_as_problem_not_silently_ok(conn):
    # No entities at all -- e.g. HA just restarted, or the collector's MQTT
    # connection is down entirely. Unlike a single sensor reading, "we
    # can't tell" here should surface as something to check, not as quietly
    # assuming everything is fine.
    health = get_collector_health(conn)

    assert health.is_problem is True
    assert health.status is None


def test_get_collector_health_treats_unavailable_state_as_problem(conn):
    now = datetime(2026, 8, 8, 8, 0, tzinfo=LOCAL_TZ)
    _add_entity(conn, 1, "binary_sensor.govee_collector_problem")
    _add_state(conn, 1, "unavailable", now)
    _add_entity(conn, 2, "sensor.govee_collector_status")
    _add_state(conn, 2, "unavailable", now)

    health = get_collector_health(conn)

    assert health.is_problem is True
    assert health.status is None
