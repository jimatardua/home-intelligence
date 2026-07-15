"""Tests for sensitivity.py -- independent TOU "what if" lever framework."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from energy_report.disaggregation import HourDisaggregation
from energy_report.sensitivity import (
    AC_REDUCTION_PERCENT,
    billable_hours_from_disaggregation,
    build_sensitivity_table,
    tou_energy_cost_from_billable,
)

TZ = ZoneInfo("America/Denver")

# Monday, July 13 2026 -- a plain summer weekday, no holiday involved.
ON_PEAK_HOUR = datetime(2026, 7, 13, 18, tzinfo=TZ)  # 6pm, on-peak
OFF_PEAK_HOUR = datetime(2026, 7, 13, 17, tzinfo=TZ)  # 5pm, off-peak

SUMMER_ONPEAK_CENTS = 32.0834
SUMMER_OFFPEAK_CENTS = 7.1296


def _hour(hour_start, total_kwh, ac_kwh=0.0, ev_kwh=None) -> HourDisaggregation:
    ev_kwh = ev_kwh or {}
    accounted = ac_kwh + sum(ev_kwh.values())
    return HourDisaggregation(
        hour_start=hour_start,
        total_kwh=total_kwh,
        ac_kwh=ac_kwh,
        ev_kwh=ev_kwh,
        other_kwh=total_kwh - accounted,
        negative_other_flag=False,
    )


def test_billable_hours_classifies_onpeak_and_offpeak_correctly():
    hours = [_hour(ON_PEAK_HOUR, 5.0), _hour(OFF_PEAK_HOUR, 5.0)]
    billable = billable_hours_from_disaggregation(hours)
    by_start = {b.hour_start: b for b in billable}
    assert by_start[ON_PEAK_HOUR].onpeak_kwh == 5.0
    assert by_start[ON_PEAK_HOUR].offpeak_kwh == 0.0
    assert by_start[OFF_PEAK_HOUR].onpeak_kwh == 0.0
    assert by_start[OFF_PEAK_HOUR].offpeak_kwh == 5.0


def test_billable_hours_skips_hours_with_no_total_reading():
    hours_with_gap = [
        HourDisaggregation(
            hour_start=ON_PEAK_HOUR, total_kwh=None, ac_kwh=0.0, ev_kwh={}, other_kwh=None, negative_other_flag=False
        )
    ]
    assert billable_hours_from_disaggregation(hours_with_gap) == []
    assert len(billable_hours_from_disaggregation([_hour(ON_PEAK_HOUR, 5.0)])) == 1


def test_tou_energy_cost_from_billable_matches_hand_calculation():
    hours = [_hour(ON_PEAK_HOUR, 5.0), _hour(OFF_PEAK_HOUR, 5.0)]
    billable = billable_hours_from_disaggregation(hours)
    expected = (5.0 * SUMMER_ONPEAK_CENTS + 5.0 * SUMMER_OFFPEAK_CENTS) / 100.0
    assert tou_energy_cost_from_billable(billable) == pytest.approx(expected)


def test_ev_shift_lever_reports_positive_savings_when_onpeak_charging_exists():
    # 5kWh on-peak, 2kWh of which is EV charging -- shifting it off-peak
    # should show up as positive annual savings under this lever.
    hours = [_hour(ON_PEAK_HOUR, 5.0, ev_kwh={"jim": 2.0})]
    results = build_sensitivity_table(hours, days_observed=1, car_labels={"jim": "Jim's Tesla"})
    jim_lever = next(r for r in results if "Jim's Tesla" in r.name)
    assert jim_lever.annual_impact_dollars is not None
    assert jim_lever.annual_impact_dollars > 0
    assert not jim_lever.pending


def test_ev_shift_lever_reports_no_data_when_no_onpeak_charging_observed():
    # All EV charging happens off-peak already -- nothing to shift.
    hours = [_hour(OFF_PEAK_HOUR, 5.0, ev_kwh={"jim": 2.0})]
    results = build_sensitivity_table(hours, days_observed=1, car_labels={"jim": "Jim's Tesla"})
    jim_lever = next(r for r in results if "Jim's Tesla" in r.name)
    assert jim_lever.annual_impact_dollars is None
    assert "no on-peak charging observed" in jim_lever.note.lower()


def test_ac_reduction_lever_reports_positive_savings_when_onpeak_ac_exists():
    hours = [_hour(ON_PEAK_HOUR, 10.0, ac_kwh=5.8)]
    results = build_sensitivity_table(hours, days_observed=1, car_labels={})
    ac_lever = next(r for r in results if "A/C" in r.name)
    assert ac_lever.annual_impact_dollars is not None
    assert ac_lever.annual_impact_dollars > 0
    assert f"{AC_REDUCTION_PERCENT:.0f}%" in ac_lever.name


def test_ac_reduction_lever_reports_no_data_when_no_onpeak_ac_observed():
    hours = [_hour(OFF_PEAK_HOUR, 10.0, ac_kwh=5.8)]
    results = build_sensitivity_table(hours, days_observed=1, car_labels={})
    ac_lever = next(r for r in results if "A/C" in r.name)
    assert ac_lever.annual_impact_dollars is None
    assert "no on-peak a/c" in ac_lever.note.lower()


def test_pending_levers_always_present_and_marked_pending():
    results = build_sensitivity_table([], days_observed=1, car_labels={})
    names = {r.name: r for r in results}
    assert names["Run dishwasher after 10pm"].pending is True
    assert names["Run dishwasher after 10pm"].annual_impact_dollars is None
    assert names["Shift dryer to off-peak"].pending is True
    assert names["Shift dryer to off-peak"].annual_impact_dollars is None


def test_levers_are_independent_not_additive():
    """Applying the A/C lever must not change the EV lever's reported impact
    and vice versa -- each lever holds everything else at its observed
    value, so they must not interact with or depend on one another."""
    hours_ev_only = [_hour(ON_PEAK_HOUR, 5.0, ev_kwh={"jim": 2.0})]
    hours_both = [_hour(ON_PEAK_HOUR, 10.8, ac_kwh=5.8, ev_kwh={"jim": 2.0})]

    ev_only_results = build_sensitivity_table(hours_ev_only, days_observed=1, car_labels={"jim": "Jim's Tesla"})
    both_results = build_sensitivity_table(hours_both, days_observed=1, car_labels={"jim": "Jim's Tesla"})

    ev_only_impact = next(r for r in ev_only_results if "Jim's Tesla" in r.name).annual_impact_dollars
    both_impact = next(r for r in both_results if "Jim's Tesla" in r.name).annual_impact_dollars

    # Same 2kWh of on-peak EV charging shifted in both cases -> same $ impact
    # regardless of how much on-peak A/C also happened that hour.
    assert ev_only_impact == pytest.approx(both_impact)
