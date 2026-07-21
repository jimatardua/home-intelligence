"""Tests for temp_history.py -- recent outdoor temperature readings.

Same minimal in-memory recorder schema as test_usage_today.py, since
get_numeric_sensor_samples() (reused here directly) only touches
states_meta/states.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from home_dashboard.temp_history import OUTDOOR_TEMP_ENTITY, get_recent_outdoor_temps

TZ = ZoneInfo("America/Denver")


def _dt(h, m=0) -> datetime:
    return datetime(2026, 7, 21, h, m, tzinfo=TZ)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
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


def test_returns_readings_within_window(conn):
    _add_entity(conn, 1, OUTDOOR_TEMP_ENTITY)
    _add_state(conn, 1, "85.0", _dt(9))
    _add_state(conn, 1, "88.0", _dt(11))
    conn.commit()

    points = get_recent_outdoor_temps(conn, _dt(14), hours=12)
    assert [p.temp_f for p in points] == [85.0, 88.0]


def test_gap_states_are_omitted_not_zero(conn):
    _add_entity(conn, 1, OUTDOOR_TEMP_ENTITY)
    _add_state(conn, 1, "85.0", _dt(9))
    _add_state(conn, 1, "unavailable", _dt(10))
    _add_state(conn, 1, "88.0", _dt(11))
    conn.commit()

    points = get_recent_outdoor_temps(conn, _dt(14), hours=12)
    assert [p.temp_f for p in points] == [85.0, 88.0]


def test_no_data_returns_empty_list(conn):
    conn.commit()
    assert get_recent_outdoor_temps(conn, _dt(14), hours=12) == []


def test_respects_hours_window(conn):
    _add_entity(conn, 1, OUTDOOR_TEMP_ENTITY)
    _add_state(conn, 1, "70.0", _dt(0))  # 14 hours before _dt(14) -- outside a 12h window
    _add_state(conn, 1, "85.0", _dt(9))
    conn.commit()

    points = get_recent_outdoor_temps(conn, _dt(14), hours=12)
    assert [p.temp_f for p in points] == [85.0]
