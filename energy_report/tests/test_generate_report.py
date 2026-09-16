"""Tests for generate_report.py's report-context wiring.

Minimal coverage of the daily-breakdown/temperature wiring this project's
test suite didn't previously have -- not backfilling full coverage for the
pre-existing report-generation logic, just making sure the new carport
temperature wiring (added alongside the existing north-side Eve Weather
wiring) is exercised, given this project's "well-tested code is
non-negotiable" standard.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_report.billing import MonthlyCost
from energy_report.disaggregation import HourDisaggregation
from energy_report.generate_report import (
    RMP_HOURS_SINCE_SYNC_ENTITY,
    RMP_SYNC_PROBLEM_ENTITY,
    RMP_SYNC_STATUS_ENTITY,
    _current_month_snapshot,
    _daily_avg_temps,
    _daily_breakdown,
    _get_rmp_sync_health,
)
from energy_report.ha_recorder import NumericSample

TZ = ZoneInfo("America/Denver")


def _hour(d: date, h: int) -> HourDisaggregation:
    return HourDisaggregation(
        hour_start=datetime(d.year, d.month, d.day, h, tzinfo=TZ),
        total_kwh=1.0,
        ac_kwh=0.5,
        ev_kwh={"jim": 0.0, "irina": 0.0},
        other_kwh=0.5,
        negative_other_flag=False,
    )


def test_daily_avg_temps_is_source_agnostic():
    d = date(2026, 7, 20)
    samples = [
        NumericSample(at_local=datetime(2026, 7, 20, 10, tzinfo=TZ), value=80.0),
        NumericSample(at_local=datetime(2026, 7, 20, 14, tzinfo=TZ), value=90.0),
        NumericSample(at_local=datetime(2026, 7, 20, 18, tzinfo=TZ), value=None),
    ]
    result = _daily_avg_temps(samples)
    assert result == {d: 85.0}


def test_daily_avg_temps_day_with_no_real_readings_is_absent():
    samples = [NumericSample(at_local=datetime(2026, 7, 20, 10, tzinfo=TZ), value=None)]
    assert _daily_avg_temps(samples) == {}


def test_daily_breakdown_carries_both_temperature_sources_independently():
    d = date(2026, 7, 20)
    hours = [_hour(d, 10), _hour(d, 11)]
    coverage = {d: (2, 24)}
    daily_temps = {d: 91.0}  # north side, runs warm
    carport_daily_temps = {d: 80.0}  # south side

    [breakdown] = _daily_breakdown(hours, coverage, daily_temps, carport_daily_temps)
    assert breakdown.avg_outdoor_temp_f == 91.0
    assert breakdown.avg_carport_temp_f == 80.0


def test_daily_breakdown_carport_temp_missing_for_a_day_is_none():
    d = date(2026, 7, 20)
    hours = [_hour(d, 10)]
    coverage = {d: (1, 24)}
    daily_temps = {d: 91.0}
    carport_daily_temps: dict[date, float] = {}  # no car parked in the carport that day

    [breakdown] = _daily_breakdown(hours, coverage, daily_temps, carport_daily_temps)
    assert breakdown.avg_outdoor_temp_f == 91.0
    assert breakdown.avg_carport_temp_f is None


# --- _current_month_snapshot ---------------------------------------------


def _monthly_cost(year: int, month: int, energy_cost: float, customer_charge: float = 12.0) -> MonthlyCost:
    return MonthlyCost(
        year=year,
        month=month,
        season="summer",
        total_kwh=100.0,
        energy_cost_dollars=energy_cost,
        customer_charge_dollars=customer_charge,
    )


def test_current_month_snapshot_uses_latest_month_not_earliest():
    # Two months present; the later one (August) must win even though it's
    # not necessarily "today" in a real run -- see the function's own
    # docstring on why wall-clock today isn't used.
    s1_months = [_monthly_cost(2026, 7, energy_cost=27.0), _monthly_cost(2026, 8, energy_cost=9.0)]
    tou_months = [_monthly_cost(2026, 7, energy_cost=40.0), _monthly_cost(2026, 8, energy_cost=15.0)]
    coverage = {date(2026, 8, 1): (24, 24), date(2026, 8, 2): (24, 24), date(2026, 7, 15): (24, 24)}

    s1_cost, tou_cost, label, days_observed, days_in_month = _current_month_snapshot(s1_months, tou_months, coverage)

    assert s1_cost == pytest.approx(21.0)  # August only: 9.0 + 12.0 customer charge
    assert tou_cost == pytest.approx(27.0)  # August only: 15.0 + 12.0 customer charge
    assert label == "August 2026"
    assert days_observed == 2
    assert days_in_month == 31


def test_current_month_snapshot_single_day_month_reports_partial_count():
    s1_months = [_monthly_cost(2026, 9, energy_cost=1.0)]
    tou_months = [_monthly_cost(2026, 9, energy_cost=2.0)]
    coverage = {date(2026, 9, 1): (5, 24)}

    _, _, label, days_observed, days_in_month = _current_month_snapshot(s1_months, tou_months, coverage)

    assert label == "September 2026"
    assert days_observed == 1
    assert days_in_month == 30


def test_current_month_snapshot_ignores_coverage_days_from_other_months():
    s1_months = [_monthly_cost(2026, 6, energy_cost=5.0), _monthly_cost(2026, 7, energy_cost=5.0)]
    tou_months = [_monthly_cost(2026, 6, energy_cost=6.0), _monthly_cost(2026, 7, energy_cost=6.0)]
    coverage = {date(2026, 6, d): (24, 24) for d in range(1, 31)}
    coverage.update({date(2026, 7, 1): (24, 24), date(2026, 7, 2): (24, 24), date(2026, 7, 3): (24, 24)})

    *_, days_observed, _ = _current_month_snapshot(s1_months, tou_months, coverage)

    assert days_observed == 3


# --- _get_rmp_sync_health -----------------------------------------------
# Duplicates the minimal in-memory recorder-DB fixture already established
# in test_ha_recorder.py, per this project's convention of duplicating
# fixtures per test file rather than sharing them.


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


def _add_state(connection, metadata_id: int, state: str) -> None:
    connection.execute(
        "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (?, ?, ?)",
        (metadata_id, state, datetime(2026, 8, 13, tzinfo=TZ).timestamp()),
    )


def test_rmp_sync_health_ok_when_status_is_ok(conn):
    _add_entity(conn, 1, RMP_SYNC_PROBLEM_ENTITY)
    _add_entity(conn, 2, RMP_SYNC_STATUS_ENTITY)
    _add_entity(conn, 3, RMP_HOURS_SINCE_SYNC_ENTITY)
    _add_state(conn, 1, "off")
    _add_state(conn, 2, "ok")
    _add_state(conn, 3, "1.2")

    health = _get_rmp_sync_health(conn)
    assert health.is_problem is False
    assert health.status == "ok"
    assert health.hours_since_last_sync == 1.2


def test_rmp_sync_health_is_problem_when_binary_sensor_on(conn):
    _add_entity(conn, 1, RMP_SYNC_PROBLEM_ENTITY)
    _add_entity(conn, 2, RMP_SYNC_STATUS_ENTITY)
    _add_state(conn, 1, "on")
    _add_state(conn, 2, "stuck")

    health = _get_rmp_sync_health(conn)
    assert health.is_problem is True
    assert health.status == "stuck"


def test_rmp_sync_health_missing_entities_is_treated_as_a_problem():
    """A gap (entity never created, or HA just restarted) reads as 'something
    to check,' not 'everything's fine' -- same convention as
    cigar_dashboard's get_collector_health()."""
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT)")
    connection.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, last_updated_ts REAL, attributes_id INTEGER)"
    )

    health = _get_rmp_sync_health(connection)
    connection.close()

    assert health.is_problem is True
    assert health.status is None
    assert health.hours_since_last_sync is None
