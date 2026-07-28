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
    get_current_gated_temperature,
    get_device_tracker_zone_intervals,
    get_gated_temperature_samples,
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


# --- get_device_tracker_zone_intervals ------------------------------------


def test_zone_intervals_basic_entry_and_exit(conn):
    _add_entity(conn, 10, "device_tracker.jim_s_tesla_location")
    _add_state(conn, 10, "not_home", _dt(9))
    _add_state(conn, 10, "Carport", _dt(10))
    _add_state(conn, 10, "not_home", _dt(14))
    conn.commit()

    intervals = get_device_tracker_zone_intervals(
        conn, "device_tracker.jim_s_tesla_location", _dt(8), _dt(15)
    )
    carport = [iv for iv in intervals if iv.zone == "carport"]
    assert len(carport) == 1
    assert carport[0].start_local == _dt(10)
    assert carport[0].end_local == _dt(14)


def test_zone_intervals_gap_state_produces_no_interval(conn):
    _add_entity(conn, 10, "device_tracker.jim_s_tesla_location")
    _add_state(conn, 10, "carport", _dt(10))
    _add_state(conn, 10, "unavailable", _dt(11))
    _add_state(conn, 10, "not_home", _dt(12))
    conn.commit()

    intervals = get_device_tracker_zone_intervals(
        conn, "device_tracker.jim_s_tesla_location", _dt(9), _dt(13)
    )
    assert any(iv.zone == "carport" and iv.start_local == _dt(10) and iv.end_local == _dt(11) for iv in intervals)
    assert not any(iv.start_local == _dt(11) for iv in intervals)


def test_zone_intervals_unknown_entity_returns_empty(conn):
    conn.commit()
    assert get_device_tracker_zone_intervals(conn, "device_tracker.does_not_exist", _dt(9), _dt(15)) == []


def test_zone_intervals_preserves_arbitrary_zone_name(conn):
    # Not carport-specific -- any zone name is passed through verbatim.
    _add_entity(conn, 10, "device_tracker.jim_s_tesla_location")
    _add_state(conn, 10, "Work", _dt(10))
    conn.commit()

    intervals = get_device_tracker_zone_intervals(
        conn, "device_tracker.jim_s_tesla_location", _dt(9), _dt(12)
    )
    assert intervals[0].zone == "work"


def test_zone_intervals_anchors_on_state_already_in_effect_at_start(conn):
    # The car entered the carport well before the query window opens, and
    # never changes state again within the window -- _state_changes() alone
    # would see zero rows in [start, end) and report no coverage at all.
    # This is the common "parked overnight" case, not a rare edge case.
    _add_entity(conn, 10, "device_tracker.jim_s_tesla_location")
    _add_state(conn, 10, "not_home", _dt(0))
    _add_state(conn, 10, "carport", _dt(2))  # well before the window below
    conn.commit()

    intervals = get_device_tracker_zone_intervals(
        conn, "device_tracker.jim_s_tesla_location", _dt(10), _dt(14)
    )
    carport = [iv for iv in intervals if iv.zone == "carport"]
    assert len(carport) == 1
    assert carport[0].start_local == _dt(10)  # anchored at window start, not at dt(2)
    assert carport[0].end_local == _dt(14)


def test_zone_intervals_no_anchor_added_when_change_already_at_start(conn):
    # If a real state change happens to land exactly at `start`, no
    # duplicate/zero-width anchor interval should be introduced.
    _add_entity(conn, 10, "device_tracker.jim_s_tesla_location")
    _add_state(conn, 10, "not_home", _dt(9))
    _add_state(conn, 10, "carport", _dt(10))
    conn.commit()

    intervals = get_device_tracker_zone_intervals(
        conn, "device_tracker.jim_s_tesla_location", _dt(10), _dt(12)
    )
    assert len(intervals) == 1
    assert intervals[0].zone == "carport"
    assert intervals[0].start_local == _dt(10)


# --- get_gated_temperature_samples -----------------------------------------

CARPORT_SOURCES = {
    "jim": ("sensor.jim_s_tesla_outside_temperature", "device_tracker.jim_s_tesla_location"),
    "irina": ("sensor.irina_s_tesla_outside_temperature", "device_tracker.irina_s_tesla_location"),
}


def _setup_car(conn, temp_id, tracker_id, temp_states, tracker_states):
    _add_entity(conn, temp_id, CARPORT_SOURCES["jim"][0] if temp_id == 20 else CARPORT_SOURCES["irina"][0])
    for state, at in temp_states:
        _add_state(conn, temp_id, state, at)
    _add_entity(conn, tracker_id, CARPORT_SOURCES["jim"][1] if tracker_id == 21 else CARPORT_SOURCES["irina"][1])
    for state, at in tracker_states:
        _add_state(conn, tracker_id, state, at)


def test_gated_temperature_single_car_gated_by_its_own_presence(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("not_home", _dt(9)), ("carport", _dt(10)), ("not_home", _dt(13))])
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(9))
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(14))
    at_10 = [s for s in samples if s.at_local == _dt(10)][0]
    at_13 = [s for s in samples if s.at_local == _dt(13)][0]
    assert at_10.value == 80.0
    assert at_13.value is None


def test_gated_temperature_both_cars_present_averages(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("carport", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("carport", _dt(9))])
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(12))
    assert samples[0].value == 82.0


def test_gated_temperature_one_present_uses_that_cars_value_only(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("carport", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("not_home", _dt(9))])
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(12))
    assert samples[0].value == 80.0


def test_gated_temperature_neither_present_is_gap_throughout(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("not_home", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("work", _dt(9))])
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(12))
    assert all(s.value is None for s in samples)


def test_gated_temperature_present_cars_gap_reading_excluded_not_fabricated(conn):
    # Jim is present but his temp sensor is gap-state right now; Irina is
    # also present and has a real reading -- result must be Irina's real
    # value alone, not None and not a fabricated blend with a missing value.
    _setup_car(conn, 20, 21, [("unknown", _dt(9))], [("carport", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("carport", _dt(9))])
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(12))
    assert samples[0].value == 84.0


def test_gated_temperature_both_present_both_gap_is_none(conn):
    _setup_car(conn, 20, 21, [("unknown", _dt(9))], [("carport", _dt(9))])
    _setup_car(conn, 22, 23, [("unavailable", _dt(9))], [("carport", _dt(9))])
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(12))
    assert samples[0].value is None


def test_gated_temperature_anchors_presence_that_began_before_window(conn):
    # Jim entered the carport well before `start` and hasn't left -- the
    # reported temperature should be available from `start` onward, not a
    # false gap for however long ago the car actually arrived.
    _setup_car(conn, 20, 21, [("79.0", _dt(1))], [("carport", _dt(2))])
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(1))
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(10), _dt(14))
    assert samples[0].at_local == _dt(10)
    assert samples[0].value == 79.0


def test_gated_temperature_update_while_elsewhere_still_carries_forward_once_present(conn):
    # A temp update fires at dt(10) while Jim is confirmed elsewhere (not an
    # event that should change the gated output then), but that value must
    # still be the one used via zero-order-hold once he later enters the
    # carport at dt(12), rather than being lost.
    _setup_car(
        conn,
        20,
        21,
        [("70.0", _dt(9)), ("77.0", _dt(10))],
        [("not_home", _dt(9)), ("carport", _dt(12))],
    )
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(9))
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "carport", _dt(9), _dt(14))
    assert not any(s.at_local == _dt(10) for s in samples)  # not a spurious event
    at_12 = [s for s in samples if s.at_local == _dt(12)][0]
    assert at_12.value == 77.0


def test_gated_temperature_unrecognized_zone_yields_all_gap(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("carport", _dt(9))])
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(9))
    conn.commit()

    samples = get_gated_temperature_samples(conn, CARPORT_SOURCES, "garage", _dt(9), _dt(12))
    assert all(s.value is None for s in samples)


# --- get_current_gated_temperature ------------------------------------------


def test_current_gated_temperature_present_car_resolves(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("carport", _dt(9))])
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(9))
    conn.commit()

    assert get_current_gated_temperature(conn, CARPORT_SOURCES, "carport") == 80.0


def test_current_gated_temperature_both_present_averages(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("carport", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("carport", _dt(9))])
    conn.commit()

    assert get_current_gated_temperature(conn, CARPORT_SOURCES, "carport") == 82.0


def test_current_gated_temperature_neither_present_is_none(conn):
    _setup_car(conn, 20, 21, [("80.0", _dt(9))], [("not_home", _dt(9))])
    _setup_car(conn, 22, 23, [("84.0", _dt(9))], [("work", _dt(9))])
    conn.commit()

    assert get_current_gated_temperature(conn, CARPORT_SOURCES, "carport") is None


def test_current_gated_temperature_present_but_gap_reading_falls_back(conn):
    _setup_car(conn, 20, 21, [("unavailable", _dt(9))], [("carport", _dt(9))])
    _add_entity(conn, 22, CARPORT_SOURCES["irina"][0])
    _add_entity(conn, 23, CARPORT_SOURCES["irina"][1])
    _add_state(conn, 23, "not_home", _dt(9))
    conn.commit()

    assert get_current_gated_temperature(conn, CARPORT_SOURCES, "carport") is None


def test_current_gated_temperature_unknown_entities_do_not_crash(conn):
    conn.commit()
    sources = {"jim": ("sensor.does_not_exist", "device_tracker.does_not_exist")}
    assert get_current_gated_temperature(conn, sources, "carport") is None
