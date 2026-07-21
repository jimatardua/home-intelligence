#!/usr/bin/env python3
"""CLI entry point: generates the home dashboard (index.html + data.json).

Meant to run every 2 minutes via cron -- cheap enough (pure local DB reads
plus one NWS API call) to run that often, and the client-side page refetches
`data.json` on its own 60-second cadence in between runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import datetime as dt_module

from energy_report.ha_recorder import get_latest_attributes, get_latest_state, open_recorder_db
from home_dashboard.forecast import ForecastError, get_forecast_periods
from home_dashboard.render import (
    DashboardContext,
    ForecastPeriodView,
    TempHistoryPoint,
    render_data_json,
    render_html,
)
from home_dashboard.sun_times import get_sun_times
from home_dashboard.temp_history import get_recent_outdoor_temps
from home_dashboard.usage_today import get_usage_today

OUTDOOR_TEMP_ENTITY = "sensor.eve_weather_20ebs9901_temperature"
OUTDOOR_HUMIDITY_ENTITY = "sensor.eve_weather_20ebs9901_humidity"
OUTDOOR_BATTERY_ENTITY = "sensor.eve_weather_20ebs9901_battery"
NWS_WEATHER_ENTITY = "weather.nws_40_73657574787062_111_81042551994325_kslc"
CLIMATE_ENTITY = "climate.family_room_family_room"


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_previous_forecast(output_dir: Path) -> list[ForecastPeriodView]:
    """Reuse the last-written data.json's forecast on a transient NWS failure.

    A brief NWS outage shouldn't blank out the forecast strip -- stale
    forecast data from a few minutes ago is still far more useful than
    nothing, same "don't fabricate, but don't discard good data either"
    principle as the rest of this project.
    """
    data_path = output_dir / "data.json"
    if not data_path.exists():
        return []
    try:
        previous = json.loads(data_path.read_text(encoding="utf-8"))
        return [
            ForecastPeriodView(
                name=p["name"],
                is_daytime=p["is_daytime"],
                temperature_f=p["temperature_f"],
                short_forecast=p["short_forecast"],
                precip_probability_pct=p["precip_probability_pct"],
                icon_category=p.get("icon_category"),
            )
            for p in previous.get("forecast", [])
        ]
    except (json.JSONDecodeError, KeyError, OSError):
        return []


def _build_context(db_path: Path, output_dir: Path) -> DashboardContext:
    now_local = dt_module.datetime.now().astimezone()
    conn = open_recorder_db(db_path)

    outdoor_temp_f = _float_or_none(get_latest_state(conn, OUTDOOR_TEMP_ENTITY))
    outdoor_humidity_pct = _float_or_none(get_latest_state(conn, OUTDOOR_HUMIDITY_ENTITY))
    condition = get_latest_state(conn, NWS_WEATHER_ENTITY)

    climate_attrs = get_latest_attributes(conn, CLIMATE_ENTITY)
    hvac_mode = get_latest_state(conn, CLIMATE_ENTITY)

    usage = get_usage_today(conn, now_local)
    sun_times = get_sun_times(now_local.date())

    try:
        forecast_periods = [
            ForecastPeriodView(
                name=p.name,
                is_daytime=p.is_daytime,
                temperature_f=p.temperature_f,
                short_forecast=p.short_forecast,
                precip_probability_pct=p.precip_probability_pct,
                icon_category=p.icon_category,
            )
            for p in get_forecast_periods()
        ]
    except ForecastError:
        forecast_periods = _load_previous_forecast(output_dir)

    outdoor_battery_pct = _float_or_none(get_latest_state(conn, OUTDOOR_BATTERY_ENTITY))
    temp_history = [
        TempHistoryPoint(at_local=p.at_local, temp_f=p.temp_f)
        for p in get_recent_outdoor_temps(conn, now_local, hours=12)
    ]

    return DashboardContext(
        generated_at=now_local,
        outdoor_temp_f=outdoor_temp_f,
        outdoor_humidity_pct=outdoor_humidity_pct,
        condition=condition,
        outdoor_battery_pct=outdoor_battery_pct,
        indoor_temp_f=_float_or_none(climate_attrs.get("current_temperature")),
        indoor_humidity_pct=_float_or_none(climate_attrs.get("current_humidity")),
        hvac_mode=hvac_mode,
        hvac_action=climate_attrs.get("hvac_action"),
        setpoint_f=_float_or_none(climate_attrs.get("temperature")),
        setpoint_low_f=_float_or_none(climate_attrs.get("target_temp_low")),
        setpoint_high_f=_float_or_none(climate_attrs.get("target_temp_high")),
        sunrise=sun_times.sunrise,
        sunset=sun_times.sunset,
        usage_today_ac_kwh=usage.ac_kwh,
        usage_today_ev_kwh=usage.ev_kwh,
        forecast_periods=forecast_periods,
        outdoor_temp_history=temp_history,
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.rename(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    ctx = _build_context(args.db_path, args.output_dir)
    _atomic_write(args.output_dir / "index.html", render_html(ctx))
    _atomic_write(args.output_dir / "data.json", render_data_json(ctx))
    print(f"Wrote {args.output_dir}/index.html and data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
