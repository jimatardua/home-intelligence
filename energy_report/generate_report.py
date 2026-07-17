#!/usr/bin/env python3
"""CLI entry point: generates the RMP Standard-vs-TOU cost report.

Ties together archive_loader, ha_recorder, disaggregation, billing, and
sensitivity into the final static HTML report (render.py), written
atomically (tmp file + os.rename), matching
~/Developer/infrastructure's generate_local_bw_dashboard.py convention.

Deliberately does not try to sequence against the RMP coordinator's own
(variable-time) daily poll -- this always reports on whatever's actually on
disk as of run time, using each archive file's own `fetched_at` for "data
as of" rather than wall-clock now(). A cron run before vs. after that day's
poll just means one fewer/more day of data, never wrong data.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .archive_loader import coverage_by_date, load_archive
from .billing import compute_schedule1_cost, compute_tou_cost, total_cost
from .disaggregation import disaggregate_hour
from .ha_recorder import (
    get_binary_sensor_intervals,
    get_numeric_sensor_samples,
    get_weather_temperature_samples,
    open_recorder_db,
)
from .render import DailyBreakdown, LeverRow, ReportContext, render_report
from .sensitivity import (
    billable_hours_from_disaggregation,
    build_sensitivity_table,
    tou_energy_cost_from_billable,
)
from .tariffs import is_on_peak, season_for, tariff_for_date

import datetime as dt_module

AC_ENTITY = "binary_sensor.family_room_ac_running"
EV_ENTITIES = {"jim": "sensor.jim_s_tesla_charger_power", "irina": "sensor.irina_s_tesla_charger_power"}
EV_LABELS = {"jim": "Jim's Tesla", "irina": "Irina's Tesla"}
WEATHER_ENTITY = "weather.forecast_home"

DAYS_INSUFFICIENT = 14
DAYS_SEASONAL = 60
AVG_DAYS_PER_MONTH = 30.44
DAYS_PER_YEAR = 365.25


def _maturity_tier(day_count: int, seasons_observed: set[str]) -> str:
    if day_count < DAYS_INSUFFICIENT:
        return "insufficient"
    if day_count < DAYS_SEASONAL or len(seasons_observed) < 2:
        return "early"
    return "seasonal"


def _build_report_context(archive_dir: Path, db_path: Path) -> ReportContext:
    generated_at = dt_module.datetime.now().astimezone()
    readings = load_archive(archive_dir)

    if not readings:
        return ReportContext(
            generated_at=generated_at,
            data_as_of=None,
            day_count=0,
            date_range_start=None,
            date_range_end=None,
            hour_coverage_pct=0.0,
            seasons_observed=frozenset(),
            maturity_tier="insufficient",
            observed_schedule1_cost=0.0,
            observed_tou_cost=0.0,
            summer_monthly_projection=None,
            summer_annual_projection=None,
            winter_available=False,
            sensitivity_rows=[],
            daily_breakdown=[],
            tariff_effective_date=tariff_for_date(date.today()).effective_start,
        )

    data_as_of = max(r.fetched_at for r in readings)
    window_start = readings[0].start_local
    window_end = readings[-1].start_local + timedelta(hours=1)

    conn = open_recorder_db(db_path)
    ac_intervals = get_binary_sensor_intervals(conn, AC_ENTITY, window_start, window_end)
    ev_samples = {
        car: get_numeric_sensor_samples(conn, entity, window_start, window_end)
        for car, entity in EV_ENTITIES.items()
    }
    weather_samples = get_weather_temperature_samples(conn, WEATHER_ENTITY, window_start, window_end)

    hours = [
        disaggregate_hour(r.start_local, r.usage_kwh, ac_intervals, ev_samples) for r in readings
    ]

    schedule1_months = compute_schedule1_cost(readings)
    tou_months = compute_tou_cost(readings)
    observed_schedule1 = total_cost(schedule1_months)
    observed_tou = total_cost(tou_months)

    coverage = coverage_by_date(readings)
    day_count = len(coverage)
    hours_present_total = sum(p for p, _ in coverage.values())
    hours_expected_total = sum(e for _, e in coverage.values())
    hour_coverage_pct = (
        100.0 * hours_present_total / hours_expected_total if hours_expected_total else 0.0
    )
    date_range_start = min(coverage)
    date_range_end = max(coverage)

    seasons_observed = {season_for(d, tariff_for_date(d)) for d in coverage}
    maturity_tier = _maturity_tier(day_count, seasons_observed)

    # Projections only for summer right now -- this is the season we
    # actually have data for. Generalizing to a per-season projection
    # structure isn't worth building until winter data actually exists to
    # validate it against (see docs/tou-report.md).
    summer_monthly_projection = None
    summer_annual_projection = None
    if maturity_tier != "insufficient" and "summer" in seasons_observed:
        summer_months_s1 = [m for m in schedule1_months if m.season == "summer"]
        summer_months_tou = [m for m in tou_months if m.season == "summer"]
        if summer_months_s1 and summer_months_tou:
            latest_s1 = summer_months_s1[-1]
            latest_tou = summer_months_tou[-1]
            days_in_month = sum(
                1 for d in coverage if d.year == latest_s1.year and d.month == latest_s1.month
            )
            if days_in_month > 0:
                monthly_factor = AVG_DAYS_PER_MONTH / days_in_month
                annual_factor = DAYS_PER_YEAR / days_in_month
                summer_monthly_projection = (
                    latest_s1.energy_cost_dollars * monthly_factor + latest_s1.customer_charge_dollars,
                    latest_tou.energy_cost_dollars * monthly_factor + latest_tou.customer_charge_dollars,
                )
                summer_annual_projection = (
                    latest_s1.energy_cost_dollars * annual_factor + latest_s1.customer_charge_dollars * 12,
                    latest_tou.energy_cost_dollars * annual_factor + latest_tou.customer_charge_dollars * 12,
                )

    sensitivity_rows = [
        LeverRow(name=r.name, annual_impact_dollars=r.annual_impact_dollars, pending=r.pending, note=r.note)
        for r in build_sensitivity_table(hours, day_count, EV_LABELS)
    ]

    daily_temps = _daily_avg_temps(weather_samples)
    daily_breakdown = _daily_breakdown(hours, coverage, daily_temps)

    return ReportContext(
        generated_at=generated_at,
        data_as_of=data_as_of,
        day_count=day_count,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        hour_coverage_pct=hour_coverage_pct,
        seasons_observed=frozenset(seasons_observed),
        maturity_tier=maturity_tier,
        observed_schedule1_cost=observed_schedule1,
        observed_tou_cost=observed_tou,
        summer_monthly_projection=summer_monthly_projection,
        summer_annual_projection=summer_annual_projection,
        winter_available="winter" in seasons_observed,
        sensitivity_rows=sensitivity_rows,
        daily_breakdown=daily_breakdown,
        tariff_effective_date=tariff_for_date(date_range_end).effective_start,
    )


def _daily_avg_temps(weather_samples) -> dict[date, float]:
    """Mean outdoor temperature (°F) per local calendar date.

    Unlike EV power, temperature isn't something to integrate over time --
    a plain average of whatever readings exist that day is the right
    aggregation. A day with zero real (non-gap) readings is simply absent
    from the returned dict, so callers must treat a missing key as "no
    data" rather than defaulting to 0.
    """
    by_date = defaultdict(list)
    for s in weather_samples:
        if s.value is not None:
            by_date[s.at_local.date()].append(s.value)
    return {d: sum(vals) / len(vals) for d, vals in by_date.items()}


def _daily_breakdown(hours, coverage, daily_temps: dict[date, float]) -> list[DailyBreakdown]:
    by_date = defaultdict(list)
    for h in hours:
        by_date[h.hour_start.date()].append(h)

    billable = {bh.hour_start: bh for bh in billable_hours_from_disaggregation(hours)}

    result = []
    for d in sorted(by_date):
        day_hours = by_date[d]
        ac_kwh = sum(h.ac_kwh for h in day_hours)
        ev_kwh = sum(sum(h.ev_kwh.values()) for h in day_hours)
        other_kwh = sum(h.other_kwh for h in day_hours if h.other_kwh is not None)
        onpeak_kwh = sum(billable[h.hour_start].onpeak_kwh for h in day_hours if h.hour_start in billable)
        offpeak_kwh = sum(billable[h.hour_start].offpeak_kwh for h in day_hours if h.hour_start in billable)
        hours_present, hours_expected = coverage.get(d, (0, 24))
        result.append(
            DailyBreakdown(
                d=d,
                ac_kwh=ac_kwh,
                ev_kwh=ev_kwh,
                other_kwh=other_kwh,
                onpeak_kwh=onpeak_kwh,
                offpeak_kwh=offpeak_kwh,
                hours_present=hours_present,
                hours_expected=hours_expected,
                avg_outdoor_temp_f=daily_temps.get(d),
            )
        )
    return result


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.rename(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    ctx = _build_report_context(args.archive_dir, args.db_path)
    html = render_report(ctx)
    _atomic_write(args.output, html)
    print(f"Wrote {args.output} ({ctx.day_count} day(s) of data, tier={ctx.maturity_tier})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
