"""A/C + EV usage estimate for "today so far."

RMP's own archive lags ~2 days, so it can never show "today" -- the only
genuinely live-observable usage signals in this whole project are A/C
runtime (nameplate-based estimate) and EV charging (charger power samples),
exactly what `energy_report.disaggregation` already models for the TOU
report. This reuses that same math directly, just queried live for "since
local midnight" against the recorder DB instead of the RMP archive's
lagging dates.

Deliberately not "total house usage" -- there's no way to know that without
RMP's actual meter reading, which isn't available yet for today. Callers
must present this as what it is: an estimate of these two loads
specifically, not the whole house.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from energy_report.disaggregation import ac_kwh_for_hour, ev_kwh_for_hour
from energy_report.ha_recorder import get_binary_sensor_intervals, get_numeric_sensor_samples

AC_ENTITY = "binary_sensor.family_room_ac_running"
EV_ENTITIES = {"jim": "sensor.jim_s_tesla_charger_power", "irina": "sensor.irina_s_tesla_charger_power"}


@dataclass(frozen=True)
class UsageToday:
    ac_kwh: float
    ev_kwh: float
    as_of: datetime


def get_usage_today(conn: sqlite3.Connection, now_local: datetime) -> UsageToday:
    """A/C + EV kWh from local midnight through `now_local`.

    Queries intervals/samples with `now_local` as the window's own end
    boundary, so an on-going A/C run or charging session is naturally
    clipped to "now" rather than projected into the future -- the existing
    `ac_kwh_for_hour()`/`ev_kwh_for_hour()` need no modification for the
    current, still-in-progress hour to come out correct.
    """
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    ac_intervals = get_binary_sensor_intervals(conn, AC_ENTITY, midnight, now_local)
    ev_samples = {
        car: get_numeric_sensor_samples(conn, entity, midnight, now_local)
        for car, entity in EV_ENTITIES.items()
    }

    ac_kwh = 0.0
    ev_kwh = 0.0
    hour_start = midnight
    while hour_start < now_local:
        ac_kwh += ac_kwh_for_hour(ac_intervals, hour_start)
        for samples in ev_samples.values():
            ev_kwh += ev_kwh_for_hour(samples, hour_start)
        hour_start += timedelta(hours=1)

    return UsageToday(ac_kwh=round(ac_kwh, 2), ev_kwh=round(ev_kwh, 2), as_of=now_local)
