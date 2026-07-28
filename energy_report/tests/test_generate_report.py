"""Tests for generate_report.py's report-context wiring.

Minimal coverage of the daily-breakdown/temperature wiring this project's
test suite didn't previously have -- not backfilling full coverage for the
pre-existing report-generation logic, just making sure the new carport
temperature wiring (added alongside the existing north-side Eve Weather
wiring) is exercised, given this project's "well-tested code is
non-negotiable" standard.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from energy_report.disaggregation import HourDisaggregation
from energy_report.generate_report import _daily_avg_temps, _daily_breakdown
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
