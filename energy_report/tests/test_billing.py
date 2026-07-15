"""Tests for billing.py -- tiered Schedule 1 and TOU cost computation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from energy_report.archive_loader import HourlyReading
from energy_report.billing import compute_schedule1_cost, compute_tou_cost, total_cost

TZ = ZoneInfo("America/Denver")


def _reading(y, mo, d, h, kwh) -> HourlyReading:
    return HourlyReading(
        start_local=datetime(y, mo, d, h, tzinfo=TZ),
        usage_kwh=kwh,
        source_date=datetime(y, mo, d).date(),
        fetched_at=datetime(y, mo, d, h, tzinfo=TZ),
    )


def test_schedule1_stays_within_first_tier():
    # 10 hours x 10 kWh = 100 kWh, well under the 400 kWh summer tier-1 threshold.
    readings = [_reading(2026, 7, 1, h, 10.0) for h in range(10)]
    [month] = compute_schedule1_cost(readings)
    assert month.total_kwh == 100.0
    assert month.season == "summer"
    expected_energy = 100.0 * 9.3199 / 100.0
    assert month.energy_cost_dollars == pytest.approx(expected_energy)
    assert month.customer_charge_dollars == 12.00


def test_schedule1_crosses_into_second_tier():
    # 41 hours x 10 kWh = 410 kWh -- 400 at tier1, 10 at tier2.
    readings = [_reading(2026, 7, 1, h % 24, 10.0) for h in range(41)]
    [month] = compute_schedule1_cost(readings)
    assert month.total_kwh == 410.0
    expected_energy = (400.0 * 9.3199 + 10.0 * 12.0130) / 100.0
    assert month.energy_cost_dollars == pytest.approx(expected_energy)


def test_schedule1_winter_rate_used_for_winter_month():
    readings = [_reading(2026, 1, 1, h, 10.0) for h in range(5)]
    [month] = compute_schedule1_cost(readings)
    assert month.season == "winter"
    expected_energy = 50.0 * 8.2477 / 100.0
    assert month.energy_cost_dollars == pytest.approx(expected_energy)


def test_tou_prices_each_hour_independently_no_tiers():
    # One on-peak hour (Monday 6pm) and one off-peak hour (Monday 5pm), same day.
    on_peak = _reading(2026, 7, 13, 18, 5.0)  # Monday 6pm
    off_peak = _reading(2026, 7, 13, 17, 5.0)  # Monday 5pm
    [month] = compute_tou_cost([on_peak, off_peak])
    expected_energy = (5.0 * 32.0834 + 5.0 * 7.1296) / 100.0
    assert month.energy_cost_dollars == pytest.approx(expected_energy)


def test_tou_weekend_is_always_offpeak_even_at_6pm():
    saturday_6pm = _reading(2026, 7, 18, 18, 5.0)
    [month] = compute_tou_cost([saturday_6pm])
    expected_energy = 5.0 * 7.1296 / 100.0
    assert month.energy_cost_dollars == pytest.approx(expected_energy)


def test_total_cost_sums_across_months():
    readings = [_reading(2026, 7, 1, 0, 10.0), _reading(2026, 8, 1, 0, 10.0)]
    months = compute_schedule1_cost(readings)
    assert len(months) == 2
    assert total_cost(months) == pytest.approx(sum(m.total_cost_dollars for m in months))


def test_missing_hours_are_excluded_not_zero():
    """A month with only a few hours of real data should bill only those
    hours -- gaps must not be silently treated as 0 kWh contributing to
    tier math in some other way, and must not inflate the customer charge."""
    readings = [_reading(2026, 7, 1, 0, 50.0)]  # just one hour
    [month] = compute_schedule1_cost(readings)
    assert month.total_kwh == 50.0
    assert month.customer_charge_dollars == 12.00  # still just one customer charge
