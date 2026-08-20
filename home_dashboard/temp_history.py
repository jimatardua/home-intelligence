"""Recent outdoor temperature history, for the dashboard's sparkline.

Reuses `energy_report.ha_recorder.get_numeric_sensor_samples()` directly --
the Eve Weather sensor is a plain numeric sensor (its `state` column holds
the reading directly), the exact case that reader was already built for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from energy_report.ha_recorder import get_current_gated_temperature, get_numeric_sensor_samples

OUTDOOR_TEMP_ENTITY = "sensor.eve_weather_20ebs9901_temperature"

# The dashboard sparkline's window -- single source of truth so the query
# and the on-screen "last Nh" label (render.py) can never drift apart.
OUTDOOR_TEMP_HISTORY_HOURS = 24

# A second, independent outdoor-temperature source -- see
# energy_report/generate_report.py's CARPORT_ZONE/CARPORT_SOURCES for the
# full rationale (north sensor runs warm from patio radiant heat; carport
# reading only exists while a Tesla is actually parked there). Duplicated
# here rather than shared into a new module, matching the existing
# precedent of EV_ENTITIES being independently duplicated between
# generate_report.py and this package.
CARPORT_ZONE = "carport"
CARPORT_SOURCES = {
    "jim": ("sensor.jim_s_tesla_outside_temperature", "device_tracker.jim_s_tesla_location"),
    "irina": ("sensor.irina_s_tesla_outside_temperature", "device_tracker.irina_s_tesla_location"),
}


@dataclass(frozen=True)
class TempPoint:
    at_local: datetime
    temp_f: float


def get_recent_outdoor_temps(
    conn: sqlite3.Connection, now_local: datetime, hours: int = OUTDOOR_TEMP_HISTORY_HOURS
) -> list[TempPoint]:
    """Outdoor temperature readings from `hours` ago through `now_local`.

    Gap samples (sensor briefly unavailable) are simply omitted -- a
    sparkline should show a real trend line over the readings that exist,
    not a fabricated 0 or a broken line segment for a gap.
    """
    samples = get_numeric_sensor_samples(conn, OUTDOOR_TEMP_ENTITY, now_local - timedelta(hours=hours), now_local)
    return [TempPoint(at_local=s.at_local, temp_f=s.value) for s in samples if s.value is not None]


def get_current_carport_temp(
    conn: sqlite3.Connection, max_age: timedelta = timedelta(hours=1), now_ts: float | None = None
) -> float | None:
    """Current ambient temperature from whichever Tesla(s) are presently
    parked in the carport, averaged if both are -- None if neither is, or
    if the only reading(s) available are older than `max_age` (default 1
    hour -- a car that's been asleep longer than that shouldn't have its
    stale last-known reading presented as "the current temperature").
    `now_ts`/`max_age` just forward to get_current_gated_temperature();
    exposed here too so this wrapper stays independently testable with a
    fixed "now" rather than the real wall clock.
    """
    return get_current_gated_temperature(conn, CARPORT_SOURCES, CARPORT_ZONE, max_age=max_age, now_ts=now_ts)
