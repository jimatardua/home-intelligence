"""Rocky Mountain Power Schedule 1 tariff data -- versioned by effective date.

Rates are not static: the energy-charge sheet this data was transcribed
from (P.S.C.U. No. 52, Sheet No. 1.2) is itself a "Second Revision...
Canceling First Revision," filed 2025-10-15, effective 2025-12-01 -- RMP
had already revised these exact rates once before, and will again. Every
real usage data point this project has postdates 2025-12-01, so the single
version below covers 100% of what exists today, but billing code must keep
working correctly once RMP files the next rate case.

So this module is a dated *registry* of tariff versions, not a single set
of constants. `tariff_for_date()` looks up whichever version was actually
in effect for a given date -- billing code always asks "what applied on
this specific day," never "what's current." Adding a future rate change is
one new `TariffVersion` entry with its own `effective_start`, not a rewrite.

Source: Rocky Mountain Power, Electric Service Schedule No. 1, State of
Utah, P.S.C.U. No. 52. Customer charge from Original Sheet No. 1.1 (filed
2025-05-09, effective 2025-04-25). Energy charges and TOU option from
Second Revision of Sheet No. 1.2 (filed 2025-10-15, effective 2025-12-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache


@dataclass(frozen=True)
class TariffVersion:
    """One dated version of Schedule 1's rate structure (standard + TOU)."""

    effective_start: date

    # Shared
    customer_charge_dollars: float

    # Standard (tiered) plan -- cents per kWh, tier threshold in kWh,
    # applied per calendar-billing-month.
    summer_months: frozenset[int]  # month numbers considered "summer"
    tier_threshold_kwh: float
    standard_summer_tier1_cents: float
    standard_summer_tier2_cents: float
    standard_winter_tier1_cents: float
    standard_winter_tier2_cents: float

    # TOU option -- cents per kWh, no usage tiers, pure on/off-peak.
    tou_summer_onpeak_cents: float
    tou_summer_offpeak_cents: float
    tou_winter_onpeak_cents: float
    tou_winter_offpeak_cents: float
    # On-peak window: [onpeak_start_hour, onpeak_end_hour), Mon-Fri only,
    # excluding holidays. Hours are local (America/Denver) and refer to the
    # HOUR-START of an hourly usage bucket (e.g. hour 18 = 18:00-19:00).
    onpeak_start_hour: int = 18
    onpeak_end_hour: int = 22
    onpeak_weekdays: frozenset[int] = field(
        default_factory=lambda: frozenset({0, 1, 2, 3, 4})  # Mon-Fri, date.weekday()
    )


TARIFF_VERSIONS: list[TariffVersion] = [
    TariffVersion(
        effective_start=date(2025, 12, 1),
        customer_charge_dollars=12.00,
        summer_months=frozenset({6, 7, 8, 9}),
        tier_threshold_kwh=400.0,
        standard_summer_tier1_cents=9.3199,
        standard_summer_tier2_cents=12.0130,
        standard_winter_tier1_cents=8.2477,
        standard_winter_tier2_cents=10.6309,
        tou_summer_onpeak_cents=32.0834,
        tou_summer_offpeak_cents=7.1296,
        tou_winter_onpeak_cents=28.3924,
        tou_winter_offpeak_cents=6.3094,
    ),
]
TARIFF_VERSIONS.sort(key=lambda t: t.effective_start)


class NoTariffVersionError(Exception):
    """Raised when a date predates every known tariff version."""


def tariff_for_date(d: date) -> TariffVersion:
    """Return whichever tariff version was actually in effect on `d`."""
    applicable = [t for t in TARIFF_VERSIONS if t.effective_start <= d]
    if not applicable:
        raise NoTariffVersionError(
            f"No tariff version covers {d.isoformat()} -- earliest known "
            f"version starts {TARIFF_VERSIONS[0].effective_start.isoformat()}"
        )
    return max(applicable, key=lambda t: t.effective_start)


def season_for(d: date, tariff: TariffVersion) -> str:
    """Return "summer" or "winter" for the given date under `tariff`."""
    return "summer" if d.month in tariff.summer_months else "winter"


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th occurrence (1-indexed) of `weekday` (Mon=0..Sun=6) in a month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d = date(year, month, 1 + offset)
    return date(d.year, d.month, d.day + 7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """The last occurrence of `weekday` (Mon=0..Sun=6) in a month."""
    next_month_first = date(year + (month == 12), month % 12 + 1, 1)
    last_day = date.fromordinal(next_month_first.toordinal() - 1)
    offset = (last_day.weekday() - weekday) % 7
    return date.fromordinal(last_day.toordinal() - offset)


def _observed_fixed_date(actual: date) -> date:
    """Apply the tariff's weekend-observance shift to a fixed-date holiday.

    "When a holiday falls on a Saturday or Sunday, the Friday before the
    holiday (if the holiday falls on a Saturday) or the Monday following
    the holiday (if the holiday falls on a Sunday) will be considered a
    holiday and consequently Off-Peak."
    """
    weekday = actual.weekday()
    if weekday == 5:  # Saturday
        return date.fromordinal(actual.toordinal() - 1)
    if weekday == 6:  # Sunday
        return date.fromordinal(actual.toordinal() + 1)
    return actual


@lru_cache(maxsize=None)
def _observed_holidays_for_year(year: int) -> frozenset[date]:
    """All 8 named holidays' *observed* dates for `year`.

    Only the 4 fixed-calendar-date holidays (New Year's, Independence Day,
    Pioneer Day, Christmas) can land on a weekend and need the observance
    shift above -- the other 4 are defined as "nth Monday"/"nth Thursday"
    and are structurally always weekdays already.
    """
    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 7, 4),  # Independence Day
        date(year, 7, 24),  # Pioneer Day
        date(year, 12, 25),  # Christmas Day
    ]
    # Include both the actual calendar date (always a holiday) and, when it
    # falls on a weekend, the adjacent weekday the tariff also treats as a
    # holiday. The actual weekend date is off-peak either way (on-peak
    # excludes Sat/Sun regardless), but is_holiday() should still say "yes"
    # for the real holiday date itself, not just its weekday shadow.
    observed: set[date] = set()
    for d in fixed:
        observed.add(d)
        observed.add(_observed_fixed_date(d))
    observed.add(_nth_weekday_of_month(year, 2, 0, 3))  # Presidents Day: 3rd Mon of Feb
    observed.add(_last_weekday_of_month(year, 5, 0))  # Memorial Day: last Mon of May
    observed.add(_nth_weekday_of_month(year, 9, 0, 1))  # Labor Day: 1st Mon of Sep
    observed.add(_nth_weekday_of_month(year, 11, 3, 4))  # Thanksgiving: 4th Thu of Nov
    return frozenset(observed)


def is_holiday(d: date) -> bool:
    """True if `d` is an observed RMP holiday (including weekend-shifted dates).

    Checks the surrounding years too since a fixed-date holiday's observed
    shift can cross a year boundary (e.g. New Year's Day landing on a
    Saturday is observed the preceding Friday, Dec 31 of the prior year).
    """
    for year in (d.year - 1, d.year, d.year + 1):
        if d in _observed_holidays_for_year(year):
            return True
    return False


def is_on_peak(dt_local: datetime, tariff: TariffVersion) -> bool:
    """True if `dt_local` (hour-start, local time) falls in the on-peak window."""
    if is_holiday(dt_local.date()):
        return False
    if dt_local.weekday() not in tariff.onpeak_weekdays:
        return False
    return tariff.onpeak_start_hour <= dt_local.hour < tariff.onpeak_end_hour
