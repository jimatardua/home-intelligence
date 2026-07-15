"""Tests for tariffs.py -- holiday shifting, tariff versioning, on-peak logic."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

import pytest

from energy_report.tariffs import (
    TARIFF_VERSIONS,
    NoTariffVersionError,
    is_holiday,
    is_on_peak,
    season_for,
    tariff_for_date,
)


def test_tariff_for_date_returns_current_version():
    t = tariff_for_date(date(2026, 7, 13))
    assert t.effective_start == date(2025, 12, 1)


def test_tariff_for_date_raises_before_earliest_version():
    with pytest.raises(NoTariffVersionError):
        tariff_for_date(date(2020, 1, 1))


def test_tariff_version_lookup_at_boundary():
    """A second, synthetic future version must not affect dates before it,
    and must apply to dates on/after its own effective_start -- this is the
    whole point of the versioned registry (a future rate change is a new
    entry, not a rewrite that would silently reprice old data)."""
    future_version = replace(
        TARIFF_VERSIONS[0],
        effective_start=date(2027, 1, 1),
        customer_charge_dollars=99.00,
    )
    versions = TARIFF_VERSIONS + [future_version]

    def lookup(d: date):
        applicable = [t for t in versions if t.effective_start <= d]
        return max(applicable, key=lambda t: t.effective_start)

    before = lookup(date(2026, 12, 31))
    on_boundary = lookup(date(2027, 1, 1))
    after = lookup(date(2027, 6, 1))

    assert before.customer_charge_dollars == 12.00
    assert on_boundary.customer_charge_dollars == 99.00
    assert after.customer_charge_dollars == 99.00


def test_season_boundaries():
    tariff = tariff_for_date(date(2026, 1, 1))
    assert season_for(date(2026, 6, 1), tariff) == "summer"
    assert season_for(date(2026, 9, 30), tariff) == "summer"
    assert season_for(date(2026, 10, 1), tariff) == "winter"
    assert season_for(date(2026, 5, 31), tariff) == "winter"


@pytest.mark.parametrize(
    "actual_date,expect_holiday_dates",
    [
        # Independence Day 2026 falls on a Saturday -> observed Friday July 3
        (date(2026, 7, 4), [date(2026, 7, 4), date(2026, 7, 3)]),
        # New Year's Day 2027 falls on a Friday -> no shift, just itself
        (date(2027, 1, 1), [date(2027, 1, 1)]),
    ],
)
def test_holiday_weekend_observance_shift(actual_date, expect_holiday_dates):
    for d in expect_holiday_dates:
        assert is_holiday(d), f"{d} should be an observed holiday for {actual_date}"


def test_new_years_day_shift_crosses_year_boundary():
    """Jan 1, 2028 is a Saturday -> observed the preceding Friday, which is
    Dec 31, 2027 -- a real cross-year-boundary case the lookup must handle."""
    assert date(2028, 1, 1).weekday() == 5  # Saturday, sanity-check the premise
    assert is_holiday(date(2028, 1, 1))
    assert is_holiday(date(2027, 12, 31))


def test_non_holiday_weekday_is_not_a_holiday():
    assert not is_holiday(date(2026, 7, 2))  # plain Thursday


def test_nth_monday_holidays_never_need_shifting():
    # Presidents Day / Memorial Day / Labor Day are defined as "nth Monday"
    # and Thanksgiving as "4th Thursday" -- these can never land on a
    # weekend, so the observance-shift logic never applies to them.
    presidents_day_2026 = date(2026, 2, 16)
    assert presidents_day_2026.weekday() == 0
    assert is_holiday(presidents_day_2026)


def test_is_on_peak_respects_weekday_hour_and_holiday():
    tariff = tariff_for_date(date(2026, 7, 13))
    monday_6pm = datetime(2026, 7, 13, 18, 0)  # Monday
    monday_10pm = datetime(2026, 7, 13, 22, 0)  # boundary, exclusive
    monday_5pm = datetime(2026, 7, 13, 17, 0)
    saturday_7pm = datetime(2026, 7, 18, 19, 0)
    observed_holiday_friday = datetime(2026, 7, 3, 19, 0)  # July 3, observed July 4th holiday

    assert is_on_peak(monday_6pm, tariff) is True
    assert is_on_peak(monday_10pm, tariff) is False
    assert is_on_peak(monday_5pm, tariff) is False
    assert is_on_peak(saturday_7pm, tariff) is False
    assert is_on_peak(observed_holiday_friday, tariff) is False


def test_dst_spring_forward_hour_is_still_classified_correctly():
    """2026-03-08 is a DST spring-forward day in America/Denver (2am->3am).
    is_on_peak works on naive local wall-clock hour labels either way, so
    this just confirms nothing throws/misbehaves across that date."""
    tariff = tariff_for_date(date(2026, 3, 8))
    before_peak = datetime(2026, 3, 8, 17, 0)  # Sunday, so off-peak regardless
    assert is_on_peak(before_peak, tariff) is False
