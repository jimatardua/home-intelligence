"""Loads Rocky Mountain Power's raw hourly-usage archive.

Reads the JSON files written by
custom_components/rocky_mountain_power/coordinator.py
(`/config/rocky_mountain_power_archive/YYYY-MM-DD.json` on domus), one file
per day, each holding that day's raw `readDate`/`readTime`/`usage` triples
exactly as RMP returned them.

The archive is gap-aware by design: RMP's own data has real missing hours
(confirmed directly against the live archive -- e.g. one day had only 17 of
24 readings), and a coordinator restart/first-poll can leave whole days
missing entirely. Every consumer of this module must treat a missing hour
as "no data," never as zero usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as time_of_day, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json

LOCAL_TZ = ZoneInfo("America/Denver")


class ArchiveError(Exception):
    """Raised for malformed archive files."""


@dataclass(frozen=True)
class HourlyReading:
    """One hour's real usage, in local (America/Denver) time."""

    start_local: datetime  # hour-start, tz-aware, LOCAL_TZ
    usage_kwh: float
    source_date: date  # the archive file's own "date" field
    fetched_at: datetime  # when the coordinator actually fetched this file


def _reading_start_local(reading_date: date, read_time: str) -> datetime:
    """Convert an hour-ending RMP reading into an hour-start local datetime.

    Mirrors custom_components/rocky_mountain_power/coordinator.py's
    `_reading_start_datetime` exactly (that module can't be imported
    directly from a standalone script outside Home Assistant's runtime, so
    this is an intentional duplication -- if RMP's hour-ending convention
    is ever found to differ from what's assumed here, fix both places).

    `readTime` is hour-ending: "03:00" covers 02:00-03:00, and "24:00"
    covers 23:00-24:00 of the *same* reading_date (it does not roll into
    the next day).
    """
    hour_ending = int(read_time.split(":")[0])
    start_hour = hour_ending - 1
    naive = datetime.combine(reading_date, time_of_day(hour=start_hour))
    return naive.replace(tzinfo=LOCAL_TZ)


def _parse_archive_file(path: Path) -> list[HourlyReading]:
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        raise ArchiveError(f"Could not read/parse {path}: {err}") from err

    try:
        source_date = date.fromisoformat(payload["date"])
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        readings = payload["readings"]
    except (KeyError, ValueError) as err:
        raise ArchiveError(f"Unexpected archive file shape in {path}: {err}") from err

    out = []
    for r in readings:
        try:
            read_date = date.fromisoformat(r["readDate"])
            start_local = _reading_start_local(read_date, r["readTime"])
            usage_kwh = float(r["usage"])
        except (KeyError, ValueError) as err:
            raise ArchiveError(f"Unexpected reading shape in {path}: {r} ({err})") from err
        out.append(
            HourlyReading(
                start_local=start_local,
                usage_kwh=usage_kwh,
                source_date=source_date,
                fetched_at=fetched_at,
            )
        )
    return out


def load_archive(archive_dir: Path) -> list[HourlyReading]:
    """Load every archive file in `archive_dir`, sorted by hour."""
    readings: list[HourlyReading] = []
    for path in sorted(archive_dir.glob("*.json")):
        readings.extend(_parse_archive_file(path))
    readings.sort(key=lambda r: r.start_local)
    return readings


def expected_hours_for_date(d: date) -> list[datetime]:
    """The 24 hour-start local datetimes a fully-complete day would have."""
    return [
        datetime.combine(d, time_of_day(hour=h)).replace(tzinfo=LOCAL_TZ) for h in range(24)
    ]


def coverage_by_date(readings: list[HourlyReading]) -> dict[date, tuple[int, int]]:
    """Return {date: (hours_present, hours_expected)} per source_date.

    `hours_expected` is always 24, computed via naive wall-clock hour
    labels ("00:00".."23:00"), matching how RMP itself appears to label
    readings (by readTime string, not elapsed UTC time). This is a known
    simplification on the two DST-transition days a year: spring-forward
    will show a false 1-hour "gap" (23:00 wall-clock hours actually
    elapsed but 24 expected), and fall-back will silently merge the
    repeated hour rather than expecting 25. Not worth over-engineering for
    2 days/year with a one-hour, low-cost discrepancy -- flagged here so
    it's a documented choice, not a silent bug.
    """
    by_date: dict[date, set[datetime]] = {}
    for r in readings:
        by_date.setdefault(r.source_date, set()).add(r.start_local)

    result: dict[date, tuple[int, int]] = {}
    for d, hours_present in by_date.items():
        expected = len(expected_hours_for_date(d))
        result[d] = (len(hours_present), expected)
    return result
