"""Tests for usage_today.py -- live "since midnight" A/C + EV estimate.

Builds the same minimal in-memory recorder schema energy_report's own
ha_recorder tests use, since get_binary_sensor_intervals()/
get_numeric_sensor_samples() (reused here directly) only ever touch
states_meta/states, never state_attributes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from energy_report.disaggregation import AC_ESTIMATED_KW
from home_dashboard.usage_today import AC_ENTITY, EV_ENTITIES, get_usage_today

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


def test_no_data_returns_zero_not_a_crash(conn):
    conn.commit()
    usage = get_usage_today(conn, _dt(14, 30))
    assert usage.ac_kwh == 0.0
    assert usage.ev_kwh == 0.0
    assert usage.as_of == _dt(14, 30)


def test_ac_full_hours_since_midnight(conn):
    _add_entity(conn, 1, AC_ENTITY)
    _add_state(conn, 1, "off", _dt(0, 0))
    _add_state(conn, 1, "on", _dt(10, 0))
    _add_state(conn, 1, "off", _dt(12, 0))
    conn.commit()

    usage = get_usage_today(conn, _dt(14, 0))
    assert usage.ac_kwh == pytest.approx(2 * AC_ESTIMATED_KW)


def test_ac_ongoing_partial_current_hour_clips_to_now(conn):
    # AC turns on at 14:00 and is still running -- "now" is 14:30, so only
    # a half hour should count, not the full hour.
    _add_entity(conn, 1, AC_ENTITY)
    _add_state(conn, 1, "on", _dt(14, 0))
    conn.commit()

    usage = get_usage_today(conn, _dt(14, 30))
    assert usage.ac_kwh == pytest.approx(0.5 * AC_ESTIMATED_KW)


def test_ev_charging_since_midnight(conn):
    _add_entity(conn, 2, EV_ENTITIES["jim"])
    _add_state(conn, 2, "7.0", _dt(9, 0))
    _add_state(conn, 2, "0.0", _dt(11, 0))
    conn.commit()

    usage = get_usage_today(conn, _dt(14, 0))
    assert usage.ev_kwh == pytest.approx(7.0 * 2)  # 7kW held for 2 hours


def test_both_cars_summed(conn):
    _add_entity(conn, 2, EV_ENTITIES["jim"])
    _add_entity(conn, 3, EV_ENTITIES["irina"])
    _add_state(conn, 2, "7.0", _dt(9, 0))
    _add_state(conn, 2, "0.0", _dt(10, 0))
    _add_state(conn, 3, "3.0", _dt(9, 0))
    _add_state(conn, 3, "0.0", _dt(10, 0))
    conn.commit()

    usage = get_usage_today(conn, _dt(14, 0))
    assert usage.ev_kwh == pytest.approx(7.0 + 3.0)


def test_gap_state_does_not_crash_and_contributes_nothing(conn):
    _add_entity(conn, 1, AC_ENTITY)
    _add_state(conn, 1, "unavailable", _dt(10, 0))
    conn.commit()

    usage = get_usage_today(conn, _dt(14, 0))
    assert usage.ac_kwh == 0.0
