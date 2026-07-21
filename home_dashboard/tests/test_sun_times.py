"""Tests for sun_times.py -- independent sunrise/sunset, not read from HA.

sun.sun's rich attributes (next_rising/next_setting) are never persisted to
HA's recorder DB -- confirmed live against 5+ historical rows, every one
holding only `friendly_name`. So this computes sunrise/sunset directly from
the house's own lat/long instead, with zero HA dependency.
"""

from __future__ import annotations

from datetime import date

from home_dashboard.sun_times import get_sun_times


def test_sunrise_before_sunset_same_day():
    times = get_sun_times(date(2026, 7, 21))
    assert times.sunrise.date() == date(2026, 7, 21)
    assert times.sunrise < times.sunset


def test_matches_hand_checked_reference_for_known_date():
    """Cross-checked live against the actual Carrot Weather screenshot the
    user provided for this exact date/location: sunrise 6:14 AM, sunset
    8:54 PM. astral 1.6.1 (what's actually installed on domus via apt --
    confirmed live, not the newer 3.x API originally developed against)
    computes 6:13:32 AM and 8:53:48 PM for this date -- a ~1 minute
    difference from Carrot's own source, not worth chasing exactly; this
    is really just confirming the wrapper calls astral correctly for the
    house's own coordinates, not re-deriving sunrise/sunset math from
    scratch or asserting exact agreement between two different
    implementations.
    """
    times = get_sun_times(date(2026, 7, 21))
    assert times.sunrise.hour == 6
    assert 12 <= times.sunrise.minute <= 15
    assert times.sunset.hour == 20
    assert 50 <= times.sunset.minute <= 55


def test_defaults_to_today_when_no_date_given():
    explicit = get_sun_times(date.today())
    implicit = get_sun_times()
    assert explicit.sunrise.date() == implicit.sunrise.date()


def test_returned_datetimes_are_local_timezone_aware():
    times = get_sun_times(date(2026, 7, 21))
    assert times.sunrise.tzinfo is not None
    assert str(times.sunrise.tzinfo) == "America/Denver"
