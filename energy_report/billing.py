"""Bills real hourly usage under both Schedule 1 plans, tariff-version-aware.

Every calculation here looks up the tariff version and season/on-peak status
*per date/hour actually being billed* -- never "whatever's current" -- so
historical data keeps billing correctly even after RMP files a future rate
change (see tariffs.py's module docstring for why this matters).

Billing-month tiering is approximated using calendar-month boundaries
(`BILLING_CYCLE_START_DAY = 1`), since the real RMP billing-cycle start day
for this account isn't known yet. This is a one-line constant precisely so
it's easy to correct later (check a paper/PDF bill's billing period), not
because the approximation is invisible -- the report surfaces this
assumption explicitly rather than burying it.

Only hours with a real RMP reading are counted -- archive gaps are
excluded, not treated as zero usage. This means a month with data gaps will
show a genuinely lower total than what was actually used, which is the
correct conservative behavior for "observed" figures (see the data-maturity
tiers in generate_report.py) rather than silently overclaiming completeness.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .archive_loader import HourlyReading
from .tariffs import is_on_peak, season_for, tariff_for_date

# See module docstring -- calendar-month billing is an approximation until
# the account's real billing-cycle start day is confirmed.
BILLING_CYCLE_START_DAY = 1


@dataclass(frozen=True)
class MonthlyCost:
    year: int
    month: int
    season: str  # "summer" or "winter", as of the month's start date
    total_kwh: float
    energy_cost_dollars: float
    customer_charge_dollars: float

    @property
    def total_cost_dollars(self) -> float:
        return self.energy_cost_dollars + self.customer_charge_dollars


def _group_by_calendar_month(readings: list[HourlyReading]) -> dict[tuple[int, int], list[HourlyReading]]:
    by_month: dict[tuple[int, int], list[HourlyReading]] = defaultdict(list)
    for r in readings:
        by_month[(r.start_local.year, r.start_local.month)].append(r)
    return by_month


def compute_schedule1_cost(readings: list[HourlyReading]) -> list[MonthlyCost]:
    """Standard (tiered) Schedule 1 cost, grouped by calendar month."""
    results: list[MonthlyCost] = []
    for (year, month), month_readings in sorted(_group_by_calendar_month(readings).items()):
        month_start = date(year, month, 1)
        tariff = tariff_for_date(month_start)
        season = season_for(month_start, tariff)

        total_kwh = sum(r.usage_kwh for r in month_readings)
        tier1_kwh = min(total_kwh, tariff.tier_threshold_kwh)
        tier2_kwh = max(total_kwh - tariff.tier_threshold_kwh, 0.0)

        if season == "summer":
            tier1_cents, tier2_cents = tariff.standard_summer_tier1_cents, tariff.standard_summer_tier2_cents
        else:
            tier1_cents, tier2_cents = tariff.standard_winter_tier1_cents, tariff.standard_winter_tier2_cents

        energy_cost = (tier1_kwh * tier1_cents + tier2_kwh * tier2_cents) / 100.0
        results.append(
            MonthlyCost(
                year=year,
                month=month,
                season=season,
                total_kwh=total_kwh,
                energy_cost_dollars=energy_cost,
                customer_charge_dollars=tariff.customer_charge_dollars,
            )
        )
    return results


def compute_tou_cost(readings: list[HourlyReading]) -> list[MonthlyCost]:
    """TOU-option Schedule 1 cost, grouped by calendar month.

    Unlike the standard plan, TOU has no usage tiers -- each hour is priced
    independently by its own on/off-peak and season classification, so
    (unlike compute_schedule1_cost) this naturally handles a tariff version
    changing mid-month correctly with no extra work: there's nothing to
    prorate, every hour just looks up its own correct rate.
    """
    results: list[MonthlyCost] = []
    for (year, month), month_readings in sorted(_group_by_calendar_month(readings).items()):
        month_start = date(year, month, 1)
        month_tariff = tariff_for_date(month_start)  # for the customer charge only
        season = season_for(month_start, month_tariff)

        total_kwh = 0.0
        energy_cost = 0.0
        for r in month_readings:
            tariff = tariff_for_date(r.start_local.date())
            hour_season = season_for(r.start_local.date(), tariff)
            peak = is_on_peak(r.start_local, tariff)
            if hour_season == "summer":
                rate_cents = tariff.tou_summer_onpeak_cents if peak else tariff.tou_summer_offpeak_cents
            else:
                rate_cents = tariff.tou_winter_onpeak_cents if peak else tariff.tou_winter_offpeak_cents
            total_kwh += r.usage_kwh
            energy_cost += r.usage_kwh * rate_cents / 100.0

        results.append(
            MonthlyCost(
                year=year,
                month=month,
                season=season,
                total_kwh=total_kwh,
                energy_cost_dollars=energy_cost,
                customer_charge_dollars=month_tariff.customer_charge_dollars,
            )
        )
    return results


def total_cost(monthly_costs: list[MonthlyCost]) -> float:
    """Sum of total_cost_dollars across all months -- the "observed" figure."""
    return sum(m.total_cost_dollars for m in monthly_costs)
