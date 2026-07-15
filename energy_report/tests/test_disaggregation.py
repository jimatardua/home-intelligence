"""Tests for disaggregation.py -- A/C, EV, and residual "other" splitting."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_report.disaggregation import (
    AC_ESTIMATED_KW,
    ac_kwh_for_hour,
    disaggregate_hour,
    ev_kwh_for_hour,
)
from energy_report.ha_recorder import NumericSample, OnOffInterval

TZ = ZoneInfo("America/Denver")


def _dt(h, m=0) -> datetime:
    return datetime(2026, 7, 13, h, m, tzinfo=TZ)


def test_ac_kwh_for_hour_full_hour_on():
    intervals = [OnOffInterval(start_local=_dt(13), end_local=_dt(15), is_on=True)]
    assert ac_kwh_for_hour(intervals, _dt(14)) == pytest.approx(AC_ESTIMATED_KW)


def test_ac_kwh_for_hour_partial_overlap():
    # On for only the first 30 minutes of the target hour.
    intervals = [OnOffInterval(start_local=_dt(14), end_local=_dt(14, 30), is_on=True)]
    assert ac_kwh_for_hour(intervals, _dt(14)) == pytest.approx(AC_ESTIMATED_KW * 0.5)


def test_ac_kwh_for_hour_off_interval_contributes_nothing():
    intervals = [OnOffInterval(start_local=_dt(14), end_local=_dt(15), is_on=False)]
    assert ac_kwh_for_hour(intervals, _dt(14)) == 0.0


def test_ac_kwh_for_hour_no_overlap():
    intervals = [OnOffInterval(start_local=_dt(10), end_local=_dt(11), is_on=True)]
    assert ac_kwh_for_hour(intervals, _dt(14)) == 0.0


def test_ev_kwh_for_hour_sample_holds_across_hour_boundary():
    """A sample from before the target hour must still hold its value into
    it (zero-order-hold semantics) -- this is the exact cross-hour-boundary
    bug that was found and fixed in _global_step_segments."""
    samples = [
        NumericSample(at_local=_dt(13, 55), value=7.0),
        NumericSample(at_local=_dt(14, 55), value=0.0),
    ]
    # 7kW held from 13:55 to 14:55; within [14:00, 15:00) that's 55 minutes.
    expected = 7.0 * 55.0 / 60.0
    assert ev_kwh_for_hour(samples, _dt(14)) == pytest.approx(expected)


def test_ev_kwh_for_hour_none_value_contributes_nothing():
    samples = [
        NumericSample(at_local=_dt(14, 0), value=None),
        NumericSample(at_local=_dt(14, 30), value=3.0),
    ]
    # None segment [14:00, 14:30) contributes 0; 3kW segment holds from
    # 14:30 onward with no next sample to close it, so nothing after 14:30
    # is covered by _global_step_segments (no trailing segment past the
    # last sample).
    assert ev_kwh_for_hour(samples, _dt(14)) == 0.0


def test_ev_kwh_for_hour_no_samples():
    assert ev_kwh_for_hour([], _dt(14)) == 0.0


def test_disaggregate_hour_splits_total_correctly():
    ac_intervals = [OnOffInterval(start_local=_dt(14), end_local=_dt(15), is_on=True)]
    ev_samples = {
        "jim": [
            NumericSample(at_local=_dt(14), value=2.0),
            NumericSample(at_local=_dt(15), value=0.0),
        ]
    }
    result = disaggregate_hour(_dt(14), total_kwh=10.0, ac_intervals=ac_intervals, ev_samples_by_car=ev_samples)
    assert result.ac_kwh == pytest.approx(AC_ESTIMATED_KW)
    assert result.ev_kwh["jim"] == pytest.approx(2.0)
    assert result.other_kwh == pytest.approx(10.0 - AC_ESTIMATED_KW - 2.0)
    assert not result.negative_other_flag


def test_disaggregate_hour_missing_total_is_none_not_zero():
    result = disaggregate_hour(_dt(14), total_kwh=None, ac_intervals=[], ev_samples_by_car={})
    assert result.total_kwh is None
    assert result.other_kwh is None
    assert not result.negative_other_flag


def test_disaggregate_hour_clamps_negative_other_and_flags_it():
    # AC + EV estimate (5.8 + 6.0 = 11.8) exceeds the real total (10.0) --
    # estimation error, not a real negative baseline load.
    ac_intervals = [OnOffInterval(start_local=_dt(14), end_local=_dt(15), is_on=True)]
    ev_samples = {"jim": [NumericSample(at_local=_dt(14), value=6.0), NumericSample(at_local=_dt(15), value=0.0)]}
    result = disaggregate_hour(_dt(14), total_kwh=10.0, ac_intervals=ac_intervals, ev_samples_by_car=ev_samples)
    assert result.other_kwh == 0.0
    assert result.negative_other_flag is True


def test_disaggregate_hour_no_ac_or_ev_data_all_other():
    result = disaggregate_hour(_dt(14), total_kwh=1.5, ac_intervals=[], ev_samples_by_car={})
    assert result.ac_kwh == 0.0
    assert result.ev_kwh == {}
    assert result.other_kwh == pytest.approx(1.5)
    assert not result.negative_other_flag
