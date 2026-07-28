"""Tests for render.py's chart-series wiring.

Minimal coverage of the new south-side/carport temperature series added
alongside the existing north-side one -- see test_generate_report.py's
module docstring for why this is scoped narrowly rather than backfilling
full coverage of the pre-existing chart code.
"""

from __future__ import annotations

from datetime import date

from energy_report.render import DailyBreakdown, _chart_series


def _day(d: date, avg_outdoor_temp_f=None, avg_carport_temp_f=None) -> DailyBreakdown:
    return DailyBreakdown(
        d=d,
        ac_kwh=1.0,
        ev_kwh=0.0,
        other_kwh=2.0,
        onpeak_kwh=1.0,
        offpeak_kwh=2.0,
        hours_present=24,
        hours_expected=24,
        avg_outdoor_temp_f=avg_outdoor_temp_f,
        avg_carport_temp_f=avg_carport_temp_f,
    )


def test_chart_series_includes_south_temperature_alongside_north():
    daily = [
        _day(date(2026, 7, 20), avg_outdoor_temp_f=91.234, avg_carport_temp_f=80.456),
    ]
    series = _chart_series(daily)
    assert series["temp_f"] == [91.2]
    assert series["temp_f_south"] == [80.5]


def test_chart_series_south_temperature_gap_day_is_none_not_zero():
    daily = [
        _day(date(2026, 7, 20), avg_outdoor_temp_f=91.0, avg_carport_temp_f=None),
    ]
    series = _chart_series(daily)
    assert series["temp_f"] == [91.0]
    assert series["temp_f_south"] == [None]
