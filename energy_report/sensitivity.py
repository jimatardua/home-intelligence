"""Sensitivity analysis: independent "what if I changed X" TOU cost levers.

Rather than one blended "$X savings" figure, this produces a table of named
behavior changes, each with its own annual $ impact -- computed
independently, holding everything else at its actually-observed value (so
rows are interpretable as "if I only did this one thing," not additive).

Every lever here is a best-case/upper-bound estimate, not a promise: shifting
EV charging doesn't validate the car is actually home/plugged in during the
hypothetical off-peak window, and reducing A/C runtime assumes comfort is
an acceptable tradeoff. Both are re-pricing/reduction exercises applied to
*already-observed* hourly data, not a simulation of new behavior.

Two levers are implemented, scoped to data this project can actually
observe today (EV charger power, A/C on/off timing). The user's own example
also named "dishwasher after 10pm" and "shift dryer" -- there is no
monitoring for either appliance yet (no smart plugs, no circuit-level
data), so rather than fabricate numbers, those are listed as pending levers
tied to the already-planned Emporia Vue whole-home monitor
(roadmap.md Phase 3). Adding a real lever later is one new function plus
one registry entry, matching this same pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .disaggregation import HourDisaggregation
from .tariffs import is_on_peak, season_for, tariff_for_date

AC_REDUCTION_PERCENT = 10.0


@dataclass(frozen=True)
class BillableHour:
    """One hour's kWh, split by which price bucket it's billed under.

    Normally all of an hour's real kWh falls entirely into whichever bucket
    matches its actual on/off-peak timestamp. A lever can move some of it
    from one bucket to the other (a time-shift, like EV charging) or remove
    it entirely (a reduction, like less A/C runtime) without changing the
    hour's timestamp.
    """

    hour_start: datetime
    onpeak_kwh: float
    offpeak_kwh: float


@dataclass(frozen=True)
class LeverResult:
    name: str
    annual_impact_dollars: float | None  # None = insufficient data to compute
    pending: bool = False  # True = not yet implemented, needs more monitoring
    note: str = ""


def billable_hours_from_disaggregation(hours: list[HourDisaggregation]) -> list[BillableHour]:
    """Baseline billable hours: each hour priced under its own real on/off-peak status."""
    result = []
    for h in hours:
        if h.total_kwh is None:
            continue
        tariff = tariff_for_date(h.hour_start.date())
        peak = is_on_peak(h.hour_start, tariff)
        if peak:
            result.append(BillableHour(h.hour_start, onpeak_kwh=h.total_kwh, offpeak_kwh=0.0))
        else:
            result.append(BillableHour(h.hour_start, onpeak_kwh=0.0, offpeak_kwh=h.total_kwh))
    return result


def tou_energy_cost_from_billable(hours: list[BillableHour]) -> float:
    """TOU energy cost (dollars, customer charge excluded) for billable hours."""
    total = 0.0
    for h in hours:
        tariff = tariff_for_date(h.hour_start.date())
        season = season_for(h.hour_start.date(), tariff)
        if season == "summer":
            on_cents, off_cents = tariff.tou_summer_onpeak_cents, tariff.tou_summer_offpeak_cents
        else:
            on_cents, off_cents = tariff.tou_winter_onpeak_cents, tariff.tou_winter_offpeak_cents
        total += (h.onpeak_kwh * on_cents + h.offpeak_kwh * off_cents) / 100.0
    return total


def _shift_ev_to_offpeak(
    hours: list[HourDisaggregation], car_key: str
) -> list[BillableHour] | None:
    """Reclassify this car's on-peak charging kWh as off-peak, same total kWh.

    Returns None if no on-peak charging was ever observed for this car --
    the caller must render "no on-peak charging observed yet," not a
    misleading "$0 impact" that looks like timing is already optimal.
    """
    baseline = billable_hours_from_disaggregation(hours)
    ev_by_hour = {h.hour_start: h.ev_kwh.get(car_key, 0.0) for h in hours if h.total_kwh is not None}

    any_shifted = False
    shifted: list[BillableHour] = []
    for bh in baseline:
        ev_kwh = ev_by_hour.get(bh.hour_start, 0.0)
        move = min(ev_kwh, bh.onpeak_kwh)
        if move > 0:
            any_shifted = True
            shifted.append(
                BillableHour(bh.hour_start, onpeak_kwh=bh.onpeak_kwh - move, offpeak_kwh=bh.offpeak_kwh + move)
            )
        else:
            shifted.append(bh)
    return shifted if any_shifted else None


def _reduce_onpeak_ac(
    hours: list[HourDisaggregation], reduction_pct: float
) -> list[BillableHour] | None:
    """Reduce on-peak A/C kWh by `reduction_pct`, removing that energy entirely
    (a real reduction in consumption, not a time-shift like EV charging).

    Returns None if no on-peak A/C usage was ever observed.
    """
    baseline = billable_hours_from_disaggregation(hours)
    ac_by_hour = {h.hour_start: h.ac_kwh for h in hours if h.total_kwh is not None}

    any_reduced = False
    reduced: list[BillableHour] = []
    for bh in baseline:
        ac_kwh = ac_by_hour.get(bh.hour_start, 0.0)
        removable = min(ac_kwh, bh.onpeak_kwh) * (reduction_pct / 100.0)
        if removable > 0:
            any_reduced = True
            reduced.append(BillableHour(bh.hour_start, onpeak_kwh=bh.onpeak_kwh - removable, offpeak_kwh=bh.offpeak_kwh))
        else:
            reduced.append(bh)
    return reduced if any_reduced else None


def _annualize(baseline_cost: float, scenario_cost: float, days_observed: int) -> float:
    """Scale an observed-window $ difference to a full-year figure.

    Positive means the scenario *saves* money vs. the baseline TOU cost.
    """
    if days_observed <= 0:
        return 0.0
    daily_delta = (baseline_cost - scenario_cost) / days_observed
    return daily_delta * 365


def build_sensitivity_table(
    hours: list[HourDisaggregation], days_observed: int, car_labels: dict[str, str]
) -> list[LeverResult]:
    """The full lever table: implemented levers + pending (unmonitored) ones.

    `car_labels` maps the internal EV key (e.g. "jim") to a display name
    (e.g. "Jim's Tesla"), so this module doesn't need to know anything
    about which cars exist beyond what disaggregation.py already computed.
    """
    baseline_billable = billable_hours_from_disaggregation(hours)
    baseline_cost = tou_energy_cost_from_billable(baseline_billable)

    results: list[LeverResult] = []

    for car_key, label in car_labels.items():
        shifted = _shift_ev_to_offpeak(hours, car_key)
        if shifted is None:
            results.append(
                LeverResult(
                    name=f"Delay {label}'s charging to off-peak",
                    annual_impact_dollars=None,
                    note="No on-peak charging observed yet",
                )
            )
        else:
            impact = _annualize(baseline_cost, tou_energy_cost_from_billable(shifted), days_observed)
            results.append(
                LeverResult(name=f"Delay {label}'s charging to off-peak", annual_impact_dollars=impact)
            )

    reduced = _reduce_onpeak_ac(hours, AC_REDUCTION_PERCENT)
    if reduced is None:
        results.append(
            LeverResult(
                name=f"Reduce on-peak A/C runtime {AC_REDUCTION_PERCENT:.0f}%",
                annual_impact_dollars=None,
                note="No on-peak A/C usage observed yet",
            )
        )
    else:
        impact = _annualize(baseline_cost, tou_energy_cost_from_billable(reduced), days_observed)
        results.append(
            LeverResult(
                name=f"Reduce on-peak A/C runtime {AC_REDUCTION_PERCENT:.0f}%", annual_impact_dollars=impact
            )
        )

    # Pending levers: no monitoring exists for these appliances yet.
    results.append(
        LeverResult(
            name="Run dishwasher after 10pm",
            annual_impact_dollars=None,
            pending=True,
            note="Pending -- available once circuit-level monitoring exists (Emporia Vue, roadmap.md Phase 3)",
        )
    )
    results.append(
        LeverResult(
            name="Shift dryer to off-peak",
            annual_impact_dollars=None,
            pending=True,
            note="Pending -- available once circuit-level monitoring exists (Emporia Vue, roadmap.md Phase 3)",
        )
    )

    return results
