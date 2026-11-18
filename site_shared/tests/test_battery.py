from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from site_shared.battery import (
    LOW_BATTERY_PCT,
    NOT_REPORTING_GRACE_SECONDS,
    STATUS_LOW,
    STATUS_NOT_REPORTING,
    STATUS_OK,
    BatteryStatus,
    battery_alert_message,
    classify_battery,
    read_battery,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone(timedelta(hours=-7)))


def test_healthy_battery_is_ok():
    assert classify_battery("Desk", 77.0, None) == BatteryStatus("Desk", 77.0, STATUS_OK)


def test_low_threshold_is_inclusive():
    assert classify_battery("Drybox", LOW_BATTERY_PCT, None).status == STATUS_LOW
    assert classify_battery("Drybox", LOW_BATTERY_PCT + 1, None).status == STATUS_OK


def test_zero_percent_is_low_not_missing():
    status = classify_battery("Drybox", 0.0, None)

    assert status.status == STATUS_LOW
    assert status.pct == 0.0


def test_short_gap_rides_on_the_last_known_level():
    # The collector's nightly BLE reset makes every sensor unavailable for
    # about a second; that must not flash "not reporting".
    assert classify_battery("Desk", 77.0, 1.0) == BatteryStatus("Desk", 77.0, STATUS_OK)
    assert classify_battery("Drybox", 17.0, NOT_REPORTING_GRACE_SECONDS).status == STATUS_LOW


def test_gap_past_the_grace_period_is_not_reporting_and_drops_the_stale_level():
    status = classify_battery("Drybox", 4.0, NOT_REPORTING_GRACE_SECONDS + 1)

    assert status == BatteryStatus("Drybox", None, STATUS_NOT_REPORTING)


def test_sensor_that_never_reported_is_not_reporting_not_silently_ok():
    assert classify_battery("Drybox", None, None).status == STATUS_NOT_REPORTING


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
    )
    connection.execute("INSERT INTO states_meta VALUES (1, 'sensor.drybox_th02_battery')")
    yield connection
    connection.close()


def _add_state(connection, state: str, minutes_ago: float) -> None:
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (1, ?, ?)",
        (state, (NOW - timedelta(minutes=minutes_ago)).timestamp()),
    )


def test_read_battery_replays_the_real_drybox_death(conn):
    # 2026-11-17: 5% -> 4%, then silence.
    _add_state(conn, "5", 90)
    _add_state(conn, "4", 60)

    assert read_battery(conn, "sensor.drybox_th02_battery", "Drybox", NOW) == BatteryStatus("Drybox", 4.0, STATUS_LOW)

    _add_state(conn, "unavailable", 10)
    assert read_battery(conn, "sensor.drybox_th02_battery", "Drybox", NOW).status == STATUS_LOW

    conn.execute("DELETE FROM states WHERE state = 'unavailable'")
    _add_state(conn, "unavailable", 16)
    assert read_battery(conn, "sensor.drybox_th02_battery", "Drybox", NOW) == BatteryStatus(
        "Drybox", None, STATUS_NOT_REPORTING
    )


def test_read_battery_for_an_entity_the_recorder_has_never_seen(conn):
    assert read_battery(conn, "sensor.nope", "Nope", NOW).status == STATUS_NOT_REPORTING


def _b(label: str, status: str) -> BatteryStatus:
    return BatteryStatus(label, None if status == STATUS_NOT_REPORTING else 50.0, status)


def test_no_message_when_everything_is_ok():
    assert battery_alert_message([_b("Outdoor", STATUS_OK), _b("Desk", STATUS_OK)]) is None
    assert battery_alert_message([]) is None


def test_low_message_names_the_sensor():
    assert battery_alert_message([_b("Outdoor", STATUS_OK), _b("Drybox", STATUS_LOW)]) == (
        STATUS_LOW,
        "Replace Drybox batteries",
    )


def test_low_message_joins_several_sensors():
    two = [_b("Wineador", STATUS_LOW), _b("Drybox", STATUS_LOW)]
    three = two + [_b("Desk", STATUS_LOW)]

    assert battery_alert_message(two)[1] == "Replace Wineador and Drybox batteries"
    assert battery_alert_message(three)[1] == "Replace Wineador, Drybox and Desk batteries"


def test_not_reporting_message_and_pluralisation():
    assert battery_alert_message([_b("Drybox", STATUS_NOT_REPORTING)]) == (
        STATUS_NOT_REPORTING,
        "Drybox sensor not reporting",
    )
    both = [_b("Wineador", STATUS_NOT_REPORTING), _b("Drybox", STATUS_NOT_REPORTING)]
    assert battery_alert_message(both)[1] == "Wineador and Drybox sensors not reporting"


def test_a_silent_sensor_outranks_a_low_one():
    batteries = [_b("Wineador", STATUS_LOW), _b("Drybox", STATUS_NOT_REPORTING)]

    assert battery_alert_message(batteries) == (STATUS_NOT_REPORTING, "Drybox sensor not reporting")
