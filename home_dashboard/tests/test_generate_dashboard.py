"""Tests for generate_dashboard.get_batteries -- which sensors the battery
strip shows, in what order, read from a minimal fake recorder DB."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from home_dashboard.generate_dashboard import OUTDOOR_BATTERY_ENTITY, get_batteries

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone(timedelta(hours=-7)))


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
    )
    yield connection
    connection.close()


def _add(connection, metadata_id: int, entity_id: str, state: str, minutes_ago: float = 1) -> None:
    connection.execute("INSERT OR IGNORE INTO states_meta VALUES (?, ?)", (metadata_id, entity_id))
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (?, ?, ?)",
        (metadata_id, state, (NOW - timedelta(minutes=minutes_ago)).timestamp()),
    )


def test_get_batteries_outdoor_first_then_the_three_govee_sensors(conn):
    _add(conn, 1, OUTDOOR_BATTERY_ENTITY, "100")
    _add(conn, 2, "sensor.wineador_th01_battery", "83")
    _add(conn, 3, "sensor.drybox_th02_battery", "17")
    _add(conn, 4, "sensor.desk_th03_battery", "77")

    batteries = get_batteries(conn, NOW)

    assert [(b.label, b.pct, b.status) for b in batteries] == [
        ("Outdoor", 100.0, "ok"),
        ("Wineador", 83.0, "ok"),
        ("Drybox", 17.0, "low"),
        ("Desk", 77.0, "ok"),
    ]


def test_get_batteries_on_an_empty_recorder_reports_all_four_as_not_reporting(conn):
    batteries = get_batteries(conn, NOW)

    assert [b.label for b in batteries] == ["Outdoor", "Wineador", "Drybox", "Desk"]
    assert {b.status for b in batteries} == {"not_reporting"}
    assert all(b.pct is None for b in batteries)


def test_get_batteries_dead_govee_sensor_does_not_affect_the_others(conn):
    _add(conn, 1, OUTDOOR_BATTERY_ENTITY, "100")
    _add(conn, 2, "sensor.wineador_th01_battery", "83")
    _add(conn, 3, "sensor.drybox_th02_battery", "4", minutes_ago=120)
    _add(conn, 3, "sensor.drybox_th02_battery", "unavailable", minutes_ago=115)
    _add(conn, 4, "sensor.desk_th03_battery", "77")

    statuses = {b.label: b.status for b in get_batteries(conn, NOW)}

    assert statuses == {"Outdoor": "ok", "Wineador": "ok", "Drybox": "not_reporting", "Desk": "ok"}
