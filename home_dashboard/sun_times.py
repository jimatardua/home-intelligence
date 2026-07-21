"""Sunrise/sunset, computed independently of Home Assistant.

`sun.sun`'s rich attributes (`next_rising`, `next_setting`, `elevation`,
`azimuth`) are never persisted to HA's recorder DB -- confirmed live against
5+ historical rows, every one holding only `friendly_name`. Likely excluded
from recording since they'd otherwise churn constantly. So sunrise/sunset is
computed directly from the house's own lat/long via `astral` instead, with
zero HA/live-API dependency.

Uses astral's old 1.x `Location`/`.sun()` API (`Location.__init__` takes an
`(name, region, lat, lon, timezone, elevation)` tuple, `.sun(date, local)`
returns a dict of pytz-aware datetimes) -- deliberately, not astral 3.x's
newer `LocationInfo`/`astral.sun.sun()` API. domus only has `python3-astral`
1.6.1 available via apt (confirmed live); matching that rather than
reaching for `pip install --break-system-packages` to get a newer version,
consistent with how `requests` is already an apt-installed system package
here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from astral import Location

from energy_report.archive_loader import LOCAL_TZ

# Same coordinates HA itself is configured with (core.config on domus).
LATITUDE = 40.73657574787062
LONGITUDE = -111.81042551994325
ELEVATION_METERS = 1548

_LOCATION = Location(
    ("Home", "UT", LATITUDE, LONGITUDE, str(LOCAL_TZ), ELEVATION_METERS)
)


@dataclass(frozen=True)
class SunTimes:
    sunrise: datetime
    sunset: datetime


def get_sun_times(for_date: date | None = None) -> SunTimes:
    """Sunrise/sunset (local time) for the given date, defaulting to today."""
    s = _LOCATION.sun(date=for_date, local=True)
    # astral 1.x returns pytz-aware datetimes; convert to the same zoneinfo
    # tzinfo the rest of this project uses throughout, rather than mixing
    # two different tz implementations.
    return SunTimes(
        sunrise=s["sunrise"].astimezone(LOCAL_TZ),
        sunset=s["sunset"].astimezone(LOCAL_TZ),
    )
