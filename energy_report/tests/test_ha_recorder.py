"""Tests for ha_recorder.py -- states/states_meta join, gap-state handling.

Builds a minimal in-memory sqlite DB matching just enough of HA's real
recorder schema (states_meta.metadata_id/entity_id, states.metadata_id/
state/last_updated_ts) to exercise the join and time-conversion logic
directly, without needing a full HA installation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from energy_report.ha_recorder import (
    get_binary_sensor_intervals,
    get_latest_attributes,
    get_latest_state,
    get_numeric_sensor_samples,
    get_weather_temperature_samples,
)

TZ = ZoneInfo("America/Denver")


def _dt(h, m=0) -> datetime:
    return datetime(2026, 7, 13, h, m, tzinfo=TZ)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
    )
    connection.execute(
        "CREATE TABLE state_attributes (attributes_id INTEGER PRIMARY KEY, shared_attrs TEXT)"
    )
    yield connection
    connection.close()


def _add_entity(connection, metadata_id: int, entity_id: str) -> None:
    connection.execute("INSERT INTO states_meta VALUES (?, ?)", (metadata_id, entity_id))


def _add_state(connection, metadata_id: int, state: str, at_local: datetime) -> None:
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (?, ?, ?)",
        (metadata_id, state, at_local.timestamp()),
    )


def _add_weather_state(
    connection, metadata_id: int, at_local: datetime, attrs: dict, attributes_id: int
) -> None:
    connection.execute(
        "INSERT INTO state_attributes VALUES (?, ?)", (attributes_id, json.dumps(attrs))
    )
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts, attributes_id) VALUES (?, ?, ?, ?)",
        (metadata_id, "sunny", at_local.timestamp(), attributes_id),
    )


def test_binary_sensor_intervals_basic_on_off(conn):
    _add_entity(conn, 1, "binary_sensor.family_room_ac_running")
    _add_state(conn, 1, "off", _dt(10))
    _add_state(conn, 1, "on", _dt(12))
    _add_state(conn, 1, "off", _dt(14))
    conn.commit()

    intervals = get_binary_sensor_intervals(
        conn, "binary_sensor.family_room_ac_running", _dt(9), _dt(15)
    )
    on_intervals = [iv for iv in intervals if iv.is_on]
    assert len(on_intervals) == 1
    assert on_intervals[0].start_local == _dt(12)
    assert on_intervals[0].end_local == _dt(14)


def test_binary_sensor_unknown_state_produces_no_interval(conn):
    _add_entity(conn, 1, "binary_sensor.family_room_ac_running")
    _add_state(conn, 1, "on", _dt(10))
    _add_state(conn, 1, "unavailable", _dt(11))
    _add_state(conn, 1, "off", _dt(12))
    conn.commit()

    intervals = get_binary_sensor_intervals(
        conn, "binary_sensor.family_room_ac_running", _dt(9), _dt(13)
    )
    # The "unavailable" state itself yields no interval, but the "on" state
    # from 10 to 11 still does -- a gap must not erase real prior data.
    assert any(iv.is_on and iv.start_local == _dt(10) and iv.end_local == _dt(11) for iv in intervals)
    assert not any(iv.start_local == _dt(11) for iv in intervals)


def test_unknown_entity_returns_no_intervals(conn):
    conn.commit()
    assert get_binary_sensor_intervals(conn, "binary_sensor.does_not_exist", _dt(9), _dt(15)) == []


def test_numeric_sensor_samples_parses_floats(conn):
    _add_entity(conn, 2, "sensor.jim_s_tesla_charger_power")
    _add_state(conn, 2, "7.2", _dt(13))
    _add_state(conn, 2, "0.0", _dt(15))
    conn.commit()

    samples = get_numeric_sensor_samples(conn, "sensor.jim_s_tesla_charger_power", _dt(12), _dt(16))
    assert [s.value for s in samples] == [7.2, 0.0]
    assert samples[0].at_local == _dt(13)


def test_numeric_sensor_gap_states_become_none_not_zero(conn):
    _add_entity(conn, 2, "sensor.jim_s_tesla_charger_power")
    _add_state(conn, 2, "unknown", _dt(13))
    _add_state(conn, 2, "7.2", _dt(14))
    conn.commit()

    samples = get_numeric_sensor_samples(conn, "sensor.jim_s_tesla_charger_power", _dt(12), _dt(16))
    assert samples[0].value is None
    assert samples[1].value == 7.2


def test_numeric_sensor_non_numeric_garbage_becomes_none(conn):
    _add_entity(conn, 2, "sensor.jim_s_tesla_charger_power")
    _add_state(conn, 2, "not-a-number", _dt(13))
    conn.commit()

    samples = get_numeric_sensor_samples(conn, "sensor.jim_s_tesla_charger_power", _dt(12), _dt(16))
    assert samples[0].value is None


def test_weather_temperature_reads_from_attributes_not_state(conn):
    _add_entity(conn, 3, "weather.forecast_home")
    _add_weather_state(conn, 3, _dt(13), {"temperature": 98.5, "temperature_unit": "°F"}, attributes_id=1)
    _add_weather_state(conn, 3, _dt(14), {"temperature": 101.0, "temperature_unit": "°F"}, attributes_id=2)
    conn.commit()

    samples = get_weather_temperature_samples(conn, "weather.forecast_home", _dt(12), _dt(16))
    assert [s.value for s in samples] == [98.5, 101.0]
    assert samples[0].at_local == _dt(13)


def test_weather_temperature_missing_attributes_row_becomes_none(conn):
    _add_entity(conn, 3, "weather.forecast_home")
    # A state row with no matching state_attributes row at all (attributes_id
    # is NULL) -- must be a gap, not a crash or a fabricated 0.
    _add_state(conn, 3, "sunny", _dt(13))
    conn.commit()

    samples = get_weather_temperature_samples(conn, "weather.forecast_home", _dt(12), _dt(16))
    assert samples[0].value is None


def test_weather_temperature_missing_key_becomes_none(conn):
    _add_entity(conn, 3, "weather.forecast_home")
    # A real attributes row exists, but it happens to have no "temperature"
    # key -- also a gap, not a crash.
    _add_weather_state(conn, 3, _dt(13), {"humidity": 40}, attributes_id=1)
    conn.commit()

    samples = get_weather_temperature_samples(conn, "weather.forecast_home", _dt(12), _dt(16))
    assert samples[0].value is None


def test_weather_temperature_unknown_entity_returns_no_samples(conn):
    conn.commit()
    assert get_weather_temperature_samples(conn, "weather.does_not_exist", _dt(9), _dt(15)) == []


def test_get_latest_state_returns_most_recent(conn):
    _add_entity(conn, 4, "climate.family_room_family_room")
    _add_state(conn, 4, "off", _dt(10))
    _add_state(conn, 4, "cool", _dt(12))
    conn.commit()

    assert get_latest_state(conn, "climate.family_room_family_room") == "cool"


def test_get_latest_state_gap_becomes_none(conn):
    _add_entity(conn, 4, "climate.family_room_family_room")
    _add_state(conn, 4, "cool", _dt(10))
    _add_state(conn, 4, "unavailable", _dt(12))
    conn.commit()

    assert get_latest_state(conn, "climate.family_room_family_room") is None


def test_get_latest_state_unknown_entity_returns_none(conn):
    conn.commit()
    assert get_latest_state(conn, "climate.does_not_exist") is None


def test_get_latest_attributes_returns_most_recent(conn):
    _add_entity(conn, 4, "climate.family_room_family_room")
    _add_weather_state(conn, 4, _dt(10), {"current_temperature": 75}, attributes_id=1)
    _add_weather_state(conn, 4, _dt(12), {"current_temperature": 76, "temperature": 77}, attributes_id=2)
    conn.commit()

    attrs = get_latest_attributes(conn, "climate.family_room_family_room")
    assert attrs == {"current_temperature": 76, "temperature": 77}


def test_get_latest_attributes_no_attributes_row_returns_empty_dict(conn):
    _add_entity(conn, 4, "climate.family_room_family_room")
    _add_state(conn, 4, "cool", _dt(10))
    conn.commit()

    assert get_latest_attributes(conn, "climate.family_room_family_room") == {}


def test_get_latest_attributes_unknown_entity_returns_empty_dict(conn):
    conn.commit()
    assert get_latest_attributes(conn, "climate.does_not_exist") == {}
