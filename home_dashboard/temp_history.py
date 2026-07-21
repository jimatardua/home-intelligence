"""Recent outdoor temperature history, for the dashboard's sparkline.

Reuses `energy_report.ha_recorder.get_numeric_sensor_samples()` directly --
the Eve Weather sensor is a plain numeric sensor (its `state` column holds
the reading directly), the exact case that reader was already built for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

from energy_report.ha_recorder import get_numeric_sensor_samples

OUTDOOR_TEMP_ENTITY = "sensor.eve_weather_20ebs9901_temperature"


@dataclass(frozen=True)
class TempPoint:
    at_local: datetime
    temp_f: float


def get_recent_outdoor_temps(
    conn: sqlite3.Connection, now_local: datetime, hours: int = 12
) -> list[TempPoint]:
    """Outdoor temperature readings from `hours` ago through `now_local`.

    Gap samples (sensor briefly unavailable) are simply omitted -- a
    sparkline should show a real trend line over the readings that exist,
    not a fabricated 0 or a broken line segment for a gap.
    """
    samples = get_numeric_sensor_samples(conn, OUTDOOR_TEMP_ENTITY, now_local - timedelta(hours=hours), now_local)
    return [TempPoint(at_local=s.at_local, temp_f=s.value) for s in samples if s.value is not None]
