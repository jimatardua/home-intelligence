"""Read-only access to Home Assistant's recorder database.

On this HA version, `states.entity_id` is always empty (`CHAR(0)`) -- the
real entity_id lives in `states_meta`, joined via `metadata_id`.
Timestamps are UTC float epoch seconds (`last_updated_ts`). Confirmed
directly against the live database on domus, not assumed from HA's general
docs (schemas have changed across HA versions).

This module never writes to the database, and the recorder DB is opened in
SQLite's own read-only URI mode as a second layer of protection against
accidental writes -- on top of that, the DB runs in WAL mode, which is safe
for concurrent read-only access alongside HA's own recorder process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3

from .archive_loader import LOCAL_TZ

# States the recorder can report that mean "no real value," not "off"/"0".
_GAP_STATES = frozenset({"unknown", "unavailable", "none", ""})


def open_recorder_db(db_path: Path) -> sqlite3.Connection:
    """Open the recorder DB read-only -- never writes, even by accident."""
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _metadata_id(conn: sqlite3.Connection, entity_id: str) -> int | None:
    row = conn.execute(
        "SELECT metadata_id FROM states_meta WHERE entity_id = ?", (entity_id,)
    ).fetchone()
    return row[0] if row else None


def _to_local(ts: float, tz: ZoneInfo = LOCAL_TZ) -> datetime:
    return datetime.fromtimestamp(ts, tz=tz)


@dataclass(frozen=True)
class StateChange:
    """One raw state-change row, resolved to local time."""

    at_local: datetime
    state: str  # raw string; gap states are NOT filtered here, see _GAP_STATES


def _state_changes(
    conn: sqlite3.Connection, entity_id: str, start: datetime, end: datetime
) -> list[StateChange]:
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return []
    rows = conn.execute(
        """
        SELECT state, last_updated_ts
        FROM states
        WHERE metadata_id = ?
          AND last_updated_ts >= ?
          AND last_updated_ts < ?
        ORDER BY last_updated_ts
        """,
        (metadata_id, start.timestamp(), end.timestamp()),
    ).fetchall()
    return [StateChange(at_local=_to_local(ts), state=state) for state, ts in rows]


@dataclass(frozen=True)
class OnOffInterval:
    """A span of time a binary_sensor held one on/off state."""

    start_local: datetime
    end_local: datetime
    is_on: bool


def get_binary_sensor_intervals(
    conn: sqlite3.Connection, entity_id: str, start: datetime, end: datetime
) -> list[OnOffInterval]:
    """Reconstruct on/off intervals for a binary_sensor between start/end.

    Gap states (unknown/unavailable) produce no interval for that span --
    callers must not assume 100% coverage between `start` and `end`.
    """
    changes = _state_changes(conn, entity_id, start, end)
    intervals: list[OnOffInterval] = []
    for change, next_change in zip(changes, changes[1:] + [None]):
        span_end = next_change.at_local if next_change else end
        state = change.state.lower()
        if state in _GAP_STATES:
            continue
        intervals.append(
            OnOffInterval(start_local=change.at_local, end_local=span_end, is_on=state == "on")
        )
    return intervals


@dataclass(frozen=True)
class NumericSample:
    """One numeric sensor reading, or None if the state was a gap marker."""

    at_local: datetime
    value: float | None


def get_numeric_sensor_samples(
    conn: sqlite3.Connection, entity_id: str, start: datetime, end: datetime
) -> list[NumericSample]:
    """Numeric sensor samples (e.g. charger power in kW) between start/end.

    unknown/unavailable states become `value=None` -- an explicit gap, not
    a 0 reading. Non-numeric-but-not-gap states (shouldn't happen for a
    numeric sensor, but defensively) are also treated as a gap rather than
    raising, since a single malformed row shouldn't crash the whole report.
    """
    changes = _state_changes(conn, entity_id, start, end)
    samples: list[NumericSample] = []
    for change in changes:
        if change.state.lower() in _GAP_STATES:
            samples.append(NumericSample(at_local=change.at_local, value=None))
            continue
        try:
            samples.append(NumericSample(at_local=change.at_local, value=float(change.state)))
        except ValueError:
            samples.append(NumericSample(at_local=change.at_local, value=None))
    return samples


def get_weather_temperature_samples(
    conn: sqlite3.Connection, entity_id: str, start: datetime, end: datetime
) -> list[NumericSample]:
    """Outdoor temperature samples from a weather entity's `temperature` attribute.

    A weather entity's own `state` column holds a condition string (e.g.
    "sunny"), not a number -- the actual reading lives in
    `state_attributes.shared_attrs` (a JSON blob), joined via
    `states.attributes_id`. A row with no attributes, unparseable JSON, or a
    missing "temperature" key becomes `value=None` -- an explicit gap, same
    convention as `get_numeric_sensor_samples()`, never a fabricated 0.
    """
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return []
    rows = conn.execute(
        """
        SELECT sa.shared_attrs, s.last_updated_ts
        FROM states s
        LEFT JOIN state_attributes sa ON s.attributes_id = sa.attributes_id
        WHERE s.metadata_id = ?
          AND s.last_updated_ts >= ?
          AND s.last_updated_ts < ?
        ORDER BY s.last_updated_ts
        """,
        (metadata_id, start.timestamp(), end.timestamp()),
    ).fetchall()

    samples: list[NumericSample] = []
    for shared_attrs, ts in rows:
        value = None
        if shared_attrs is not None:
            try:
                value = float(json.loads(shared_attrs)["temperature"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                value = None
        samples.append(NumericSample(at_local=_to_local(ts), value=value))
    return samples


def get_latest_state(conn: sqlite3.Connection, entity_id: str) -> str | None:
    """The most recent raw state string for any entity, or None.

    None means either the entity has no recorded state at all, or its most
    recent state is a gap marker (unknown/unavailable) -- same convention
    as the rest of this module, never a fabricated value.
    """
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return None
    row = conn.execute(
        "SELECT state FROM states WHERE metadata_id = ? ORDER BY last_updated_ts DESC LIMIT 1",
        (metadata_id,),
    ).fetchone()
    if row is None or row[0].lower() in _GAP_STATES:
        return None
    return row[0]


def get_latest_attributes(conn: sqlite3.Connection, entity_id: str) -> dict:
    """The most recent full attributes dict for any entity, or {}.

    Empty dict means the entity has no recorded state, no attributes row,
    or unparseable JSON -- callers should treat missing keys as gaps, same
    convention as the rest of this module.
    """
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return {}
    row = conn.execute(
        """
        SELECT sa.shared_attrs
        FROM states s
        LEFT JOIN state_attributes sa ON s.attributes_id = sa.attributes_id
        WHERE s.metadata_id = ?
        ORDER BY s.last_updated_ts DESC LIMIT 1
        """,
        (metadata_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return {}
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return {}
