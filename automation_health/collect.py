#!/usr/bin/env python3
"""CLI entry point: counts recent HA automation/rest_command errors and
writes a Prometheus textfile-collector metric.

Meant to run every 5 minutes via cron -- matches wu_pwsweather_upload's
own trigger interval (the tightest of the two watched automations), tight
enough that every real occurrence lands in its own reading rather than
several readings sharing credit for one event.

Counts errors since the *last successful collection*, not a fixed sliding
lookback -- real incident data (2026-08-21/22) showed a 30-minute sliding
window smears a single isolated blip across up to 30 minutes of readings,
long enough to satisfy a naive "sustained >0 for 10m" Grafana alert every
time even though nothing was still broken (repeated overnight paging, see
docs/automation-health.md's "Flapping alert" section). A disjoint
delta-since-last-check window means an isolated blip is only ever visible
in the one reading that covers it -- at most one collection interval,
comfortably under a 10-minute sustained threshold -- while a genuinely
ongoing problem still shows up in every consecutive reading, since new
errors keep landing inside each new window as they happen.

On a docker-logs failure, deliberately leaves the previous `.prom` file in
place rather than writing a "0 errors" metric that would read as healthy
when the check itself just failed to run -- and leaves `last_collected_at`
unadvanced too, so the *next* successful run's window correctly widens to
cover the gap rather than silently dropping whatever happened during the
outage.
"""

from __future__ import annotations

import argparse
import datetime as dt_module
import json
import sys
from pathlib import Path

from automation_health.const import DEFAULT_LOOKBACK_MINUTES, DOCKER_CONTAINER, TEXTFILE_COLLECTOR_PATH
from automation_health.docker_log import DockerLogUnavailable, fetch_recent_log_lines
from automation_health.exporter import render_prometheus_text, write_textfile_atomically
from automation_health.log_parser import count_errors_by_automation

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_PATH = SCRIPT_DIR / "collector_state.json"


def load_state(path: Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return {"last_collected_at": data.get("last_collected_at")}
    except (OSError, json.JSONDecodeError):
        # Missing or corrupt -- treat as a first-ever run rather than
        # crashing, same gap-handling convention used throughout this
        # project (e.g. ble_auto_reset.py's own load_state()).
        return {"last_collected_at": None}


def save_state(path: Path, state: dict) -> None:
    with open(path, "w") as f:
        json.dump(state, f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--textfile-path", default=TEXTFILE_COLLECTOR_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)

    now = dt_module.datetime.now()
    state = load_state(args.state_path)
    last_collected_at = state["last_collected_at"]
    since = (
        dt_module.datetime.fromisoformat(last_collected_at)
        if last_collected_at is not None
        else now - dt_module.timedelta(minutes=DEFAULT_LOOKBACK_MINUTES)
    )
    # Enough margin past the delta window to catch anything from a slightly
    # delayed previous run, without reverting to a wide sliding window.
    lookback_minutes = max(1, int((now - since).total_seconds() // 60) + 2)

    try:
        lines = fetch_recent_log_lines(DOCKER_CONTAINER, lookback_minutes)
    except DockerLogUnavailable as err:
        print(f"automation_health: {err} -- leaving previous metric file untouched", file=sys.stderr)
        return 1

    counts = count_errors_by_automation(lines, since)
    content = render_prometheus_text(counts, now)
    write_textfile_atomically(content, args.textfile_path)
    save_state(args.state_path, {"last_collected_at": now.isoformat()})
    print(f"Wrote {args.textfile_path}: {counts} (since {since.isoformat()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
