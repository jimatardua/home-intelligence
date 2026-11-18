"""Battery status for the battery-powered sensors shown on the dashboards.

One place for the two decisions both pages make about a battery -- "is it
low?" and "has it stopped reporting?" -- so the home dashboard's battery
strip and the cigar dashboard's cards can never disagree about either.

Why two failure states rather than one: a low battery and a dead one look
nothing alike in the data. A low battery reports a small number; a dead one
reports nothing at all, so a low-battery rule alone goes quiet at exactly
the moment it matters most. See docs/home-dashboard.md, "Battery strip".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from energy_report.ha_recorder import get_last_numeric_reading

# Measured, not guessed, on the Drybox H5075's real discharge in November
# 2026 (86% -> 4% in two weeks, accelerating): it crossed 30% about 3.4
# days before reaching 5%, 20% about 19 hours before, and 10% about 5.5
# hours before. 20% is the lowest round threshold that still leaves most
# of a day to notice a wall-mounted screen; healthy sensors sat at 77-100%
# throughout, so it is also nowhere near a false alarm.
LOW_BATTERY_PCT = 20

# How long a sensor may be unavailable before it is called "not reporting".
# Until then its last known level is still shown. Measured against every
# gap in the recorder for these entities (758 for the Govee sensors, 26 for
# the Eve): 739 of the 758 were under a minute -- the collector's nightly
# and on-detection BLE resets -- and everything past 15 minutes was a real
# outage a human needed to know about.
NOT_REPORTING_GRACE_SECONDS = 15 * 60

STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_NOT_REPORTING = "not_reporting"


@dataclass(frozen=True)
class BatteryStatus:
    label: str
    pct: float | None  # None exactly when status is STATUS_NOT_REPORTING
    status: str

    def as_dict(self) -> dict:
        return {"label": self.label, "pct": self.pct, "status": self.status}


def classify_battery(label: str, last_pct: float | None, gap_seconds: float | None) -> BatteryStatus:
    """Pure decision: last known level + how long it has been silent.

    `last_pct` None means the sensor has never reported a level at all,
    which is "not reporting", not "fine" -- absent data is never treated as
    good news here.
    """
    never_reported = last_pct is None
    silent_too_long = gap_seconds is not None and gap_seconds > NOT_REPORTING_GRACE_SECONDS
    if never_reported or silent_too_long:
        return BatteryStatus(label=label, pct=None, status=STATUS_NOT_REPORTING)
    return BatteryStatus(
        label=label,
        pct=last_pct,
        status=STATUS_LOW if last_pct <= LOW_BATTERY_PCT else STATUS_OK,
    )


def read_battery(conn: sqlite3.Connection, entity_id: str, label: str, now: datetime) -> BatteryStatus:
    reading = get_last_numeric_reading(conn, entity_id, now)
    return classify_battery(label, reading.value, reading.gap_seconds)


def battery_alert_message(batteries: list[BatteryStatus]) -> tuple[str, str] | None:
    """(severity, text) for the one line of text beside the strip, or None
    when every battery is fine. Severity is STATUS_NOT_REPORTING or
    STATUS_LOW; a silent sensor outranks a low one, since it is the worse
    condition and the strip only has room for one message.
    """
    silent = [b.label for b in batteries if b.status == STATUS_NOT_REPORTING]
    if silent:
        noun = "sensor" if len(silent) == 1 else "sensors"
        return STATUS_NOT_REPORTING, f"{_join_labels(silent)} {noun} not reporting"
    low = [b.label for b in batteries if b.status == STATUS_LOW]
    if low:
        return STATUS_LOW, f"Replace {_join_labels(low)} batteries"
    return None


def _join_labels(labels: list[str]) -> str:
    if len(labels) <= 2:
        return " and ".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]
