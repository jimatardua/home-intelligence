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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3
import time

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


def _state_at_or_before(conn: sqlite3.Connection, entity_id: str, at: datetime) -> str | None:
    """Most recent raw state at or before `at`, or None if none exists.

    Unlike get_latest_state() (always "now"), this answers "what was the
    state as of this specific past instant" -- needed because
    _state_changes() only returns rows strictly inside [start, end), so an
    entity that's held the same state since before that window (e.g. a car
    parked in the carport for days without a new tracker row, since HA only
    writes a row when a state actually changes) would otherwise look like
    it never happened at all for the entire window.
    """
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return None
    row = conn.execute(
        """
        SELECT state FROM states
        WHERE metadata_id = ? AND last_updated_ts <= ?
        ORDER BY last_updated_ts DESC LIMIT 1
        """,
        (metadata_id, at.timestamp()),
    ).fetchone()
    return row[0] if row else None


def _numeric_value_at_or_before(conn: sqlite3.Connection, entity_id: str, at: datetime) -> float | None:
    """Same as _state_at_or_before(), but parsed as a number (gap-safe)."""
    raw = _state_at_or_before(conn, entity_id, at)
    if raw is None or raw.lower() in _GAP_STATES:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


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
class ZoneInterval:
    """A span of time a device_tracker held one zone state (lowercased)."""

    start_local: datetime
    end_local: datetime
    zone: str  # e.g. "carport", "home", "not_home" -- never a gap state


def get_device_tracker_zone_intervals(
    conn: sqlite3.Connection, entity_id: str, start: datetime, end: datetime
) -> list[ZoneInterval]:
    """Reconstruct zone-membership intervals for a device_tracker between start/end.

    Same reconstruction as get_binary_sensor_intervals(), but keeps the raw
    zone string (lowercased) instead of collapsing to on/off, since
    device_tracker has more than two meaningful states ("home", "not_home",
    any zone name, or a gap). Entity-id-agnostic -- not specific to any
    particular zone; callers filter for the zone they care about.

    Anchors on the state in effect at `start` itself (via
    _state_at_or_before()) when there's no change exactly at `start` --
    otherwise a device that's held the same state since before the window
    would show zero coverage for the entire window, which is wrong for the
    common case of a car parked somewhere for days without a new row.
    """
    changes = _state_changes(conn, entity_id, start, end)
    if not changes or changes[0].at_local != start:
        anchor_state = _state_at_or_before(conn, entity_id, start)
        if anchor_state is not None:
            changes = [StateChange(at_local=start, state=anchor_state)] + changes

    intervals: list[ZoneInterval] = []
    for change, next_change in zip(changes, changes[1:] + [None]):
        span_end = next_change.at_local if next_change else end
        state = change.state.lower()
        if state in _GAP_STATES:
            continue
        intervals.append(ZoneInterval(start_local=change.at_local, end_local=span_end, zone=state))
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


def get_gated_temperature_samples(
    conn: sqlite3.Connection,
    sources: dict[str, tuple[str, str]],
    zone: str,
    start: datetime,
    end: datetime,
) -> list[NumericSample]:
    """Ambient temperature reconstructed from N zone-gated sensors.

    `sources` maps an arbitrary label to (temperature_entity_id,
    tracker_entity_id) pairs. Each source's temperature only counts while
    its own device_tracker reports being in `zone`. When more than one
    source is present at a given instant, their (non-gap) values are
    averaged; when none are present, or the present source(s) all have a
    gap reading at that instant, the sample's value is None -- an explicit
    gap, never a fabricated value, same convention as the rest of this
    module.

    Correlates two independently-timestamped signals (zone membership,
    temperature updates) via an event-driven merge: computes one output
    sample at every timestamp where the gated value could change (a zone
    entry, exit, or a temperature update while already inside the zone),
    using zero-order-hold to look up each present source's temperature at
    that instant (the same assumption disaggregation.py's EV-charging
    integration already makes for charger power between samples).

    Both the zone intervals and the temperature history are anchored at
    `start` (via get_device_tracker_zone_intervals()'s and this function's
    own as-of-start lookups), so a source that's been in `zone` since
    before the window opened is still correctly recognized as present from
    `start` onward, not treated as a false gap.
    """
    zone_lc = zone.lower()

    per_car_intervals: dict[str, list[ZoneInterval]] = {}
    per_car_temps: dict[str, list[NumericSample]] = {}
    for car, (temp_entity, tracker_entity) in sources.items():
        per_car_intervals[car] = [
            iv
            for iv in get_device_tracker_zone_intervals(conn, tracker_entity, start, end)
            if iv.zone == zone_lc
        ]

        temps = get_numeric_sensor_samples(conn, temp_entity, start, end)
        if not temps or temps[0].at_local != start:
            anchor_value = _numeric_value_at_or_before(conn, temp_entity, start)
            temps = [NumericSample(at_local=start, value=anchor_value)] + temps
        per_car_temps[car] = temps

    def present_at(car: str, t: datetime) -> bool:
        return any(iv.start_local <= t < iv.end_local for iv in per_car_intervals[car])

    def value_at(car: str, t: datetime) -> float | None:
        value = None
        for s in per_car_temps[car]:
            if s.at_local > t:
                break
            value = s.value
        return value

    def gated_value_at(t: datetime) -> float | None:
        present_values = [value_at(car, t) for car in sources if present_at(car, t)]
        real = [v for v in present_values if v is not None]
        return sum(real) / len(real) if real else None

    event_times = {start}
    for car in sources:
        for iv in per_car_intervals[car]:
            if start <= iv.start_local < end:
                event_times.add(iv.start_local)
            if start <= iv.end_local < end:
                event_times.add(iv.end_local)
        for s in per_car_temps[car]:
            if start <= s.at_local < end and present_at(car, s.at_local):
                event_times.add(s.at_local)

    return [NumericSample(at_local=t, value=gated_value_at(t)) for t in sorted(event_times)]


def _latest_state_with_timestamp(conn: sqlite3.Connection, entity_id: str) -> tuple[str | None, float | None]:
    """Same as get_latest_state(), but also returns the raw UTC epoch
    timestamp of that reading (None if the entity has no recorded state at
    all). The state itself still follows the same gap convention (None for
    a gap marker), independent of the timestamp -- a caller reasoning about
    staleness needs the age even when the value itself turns out to be a
    gap.
    """
    metadata_id = _metadata_id(conn, entity_id)
    if metadata_id is None:
        return None, None
    row = conn.execute(
        "SELECT state, last_updated_ts FROM states WHERE metadata_id = ? ORDER BY last_updated_ts DESC LIMIT 1",
        (metadata_id,),
    ).fetchone()
    if row is None:
        return None, None
    state, ts = row
    if state.lower() in _GAP_STATES:
        return None, ts
    return state, ts


def get_current_gated_temperature(
    conn: sqlite3.Connection,
    sources: dict[str, tuple[str, str]],
    zone: str,
    max_age: timedelta = timedelta(hours=1),
    now_ts: float | None = None,
) -> float | None:
    """Current ambient temperature from whichever gated source(s) are
    presently in `zone`, averaged if more than one.

    Built on get_latest_state() (most-recent-only, unbounded lookback) --
    not the windowed reconstruction above -- because a source that's been
    in `zone` for hours without a new tracker row must still read as
    present, not as a gap the way a narrow recent time window would.

    A present source's temperature reading only counts if it's no older
    than `max_age` (default 1 hour). Once a car's been asleep long enough
    that its last-known reading exceeds this, presenting it as "the
    current temperature" would be actively misleading -- real outdoor
    temperature can change meaningfully over that span -- so it's excluded
    entirely rather than shown as if it were fresh. `now_ts` (a raw UTC
    epoch, matching this module's `last_updated_ts` convention) defaults to
    the real current time; overridable for deterministic tests.
    """
    if now_ts is None:
        now_ts = time.time()
    zone_lc = zone.lower()
    present_values: list[float] = []
    for temp_entity, tracker_entity in sources.values():
        zone_state = get_latest_state(conn, tracker_entity)
        if zone_state is None or zone_state.lower() != zone_lc:
            continue
        temp_state, temp_ts = _latest_state_with_timestamp(conn, temp_entity)
        if temp_state is None or temp_ts is None:
            continue
        if now_ts - temp_ts > max_age.total_seconds():
            continue
        try:
            present_values.append(float(temp_state))
        except ValueError:
            continue
    return sum(present_values) / len(present_values) if present_values else None
