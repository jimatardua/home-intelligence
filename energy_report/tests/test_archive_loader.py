"""Tests for archive_loader.py -- hour-ending conversion, gaps, coverage."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from energy_report.archive_loader import (
    ArchiveError,
    LOCAL_TZ,
    coverage_by_date,
    expected_hours_for_date,
    load_archive,
)


def _write_archive_file(dir_path: Path, source_date: str, fetched_at: str, readings: list[dict]) -> None:
    payload = {"date": source_date, "fetched_at": fetched_at, "readings": readings}
    (dir_path / f"{source_date}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_hour_ending_conversion_is_one_hour_before_readtime(tmp_path):
    # readTime "03:00" (hour-ending) covers 02:00-03:00 -> start_local 02:00.
    _write_archive_file(
        tmp_path,
        "2026-07-13",
        "2026-07-14T05:00:00+00:00",
        [{"readDate": "2026-07-13", "readTime": "03:00", "usage": 1.23}],
    )
    [reading] = load_archive(tmp_path)
    assert reading.start_local == datetime(2026, 7, 13, 2, 0, tzinfo=LOCAL_TZ)
    assert reading.usage_kwh == 1.23


def test_hour_ending_24_00_stays_within_same_day():
    from energy_report.archive_loader import _reading_start_local

    start = _reading_start_local(date(2026, 7, 13), "24:00")
    assert start == datetime(2026, 7, 13, 23, 0, tzinfo=LOCAL_TZ)


def test_load_archive_sorts_across_multiple_files(tmp_path):
    _write_archive_file(
        tmp_path, "2026-07-14", "2026-07-15T05:00:00+00:00",
        [{"readDate": "2026-07-14", "readTime": "01:00", "usage": 2.0}],
    )
    _write_archive_file(
        tmp_path, "2026-07-13", "2026-07-14T05:00:00+00:00",
        [{"readDate": "2026-07-13", "readTime": "01:00", "usage": 1.0}],
    )
    readings = load_archive(tmp_path)
    assert [r.start_local.date() for r in readings] == [date(2026, 7, 13), date(2026, 7, 14)]


def test_malformed_json_raises_archive_error(tmp_path):
    (tmp_path / "2026-07-13.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ArchiveError):
        load_archive(tmp_path)


def test_missing_required_field_raises_archive_error(tmp_path):
    (tmp_path / "2026-07-13.json").write_text(
        json.dumps({"date": "2026-07-13", "fetched_at": "2026-07-14T05:00:00+00:00"}), encoding="utf-8"
    )
    with pytest.raises(ArchiveError):
        load_archive(tmp_path)


def test_expected_hours_for_date_has_24_entries():
    hours = expected_hours_for_date(date(2026, 7, 13))
    assert len(hours) == 24
    assert hours[0] == datetime(2026, 7, 13, 0, tzinfo=LOCAL_TZ)
    assert hours[-1] == datetime(2026, 7, 13, 23, tzinfo=LOCAL_TZ)


def test_coverage_by_date_reports_partial_day_gap(tmp_path):
    # Only 2 of 24 hours present -- a real gap must be visible, not hidden.
    _write_archive_file(
        tmp_path, "2026-07-13", "2026-07-14T05:00:00+00:00",
        [
            {"readDate": "2026-07-13", "readTime": "01:00", "usage": 1.0},
            {"readDate": "2026-07-13", "readTime": "02:00", "usage": 1.0},
        ],
    )
    readings = load_archive(tmp_path)
    coverage = coverage_by_date(readings)
    assert coverage[date(2026, 7, 13)] == (2, 24)


def test_coverage_by_date_full_day():
    readings = []
    from energy_report.archive_loader import HourlyReading

    for h in expected_hours_for_date(date(2026, 7, 13)):
        readings.append(
            HourlyReading(
                start_local=h, usage_kwh=1.0, source_date=date(2026, 7, 13),
                fetched_at=datetime(2026, 7, 14, 5, tzinfo=LOCAL_TZ),
            )
        )
    coverage = coverage_by_date(readings)
    assert coverage[date(2026, 7, 13)] == (24, 24)
