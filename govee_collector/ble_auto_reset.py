#!/usr/bin/env python3
"""CLI entry point: detects `collector.py`'s "stuck" BLE health status and
runs `ble_nightly_reset.sh` automatically -- the on-detection counterpart
to the existing nightly preemptive reset (see docs/govee-cigar-monitor.md).

Meant to run every 2 minutes via cron on mrteeny. Detection is entirely
local (parses this host's own `journalctl -u govee-collector`, not HA's
REST API or MQTT) -- deliberately no dependency on cross-host reachability,
the same reasoning `automation_health` used `docker logs` for on domus.

Reuses `collector.py`'s own stale/stuck thresholds by parsing its
"Collector health: <status>" log line rather than re-deriving them here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESET_SCRIPT = SCRIPT_DIR / "ble_nightly_reset.sh"
DEFAULT_STATE_PATH = SCRIPT_DIR / "auto_reset_state.json"

SYSTEMD_UNIT = "govee-collector"
DEFAULT_LOOKBACK_MINUTES = 5

STUCK = "stuck"

# Mirrors the tiered backoff built for automation_health's weather-upload
# automations (docs/automation-health.md) -- same reasoning: if a reset
# doesn't actually fix it, retrying every 2 minutes forever isn't right
# (excessive bluetoothd restarts, and it means something worse than the
# known transient wedge is going on). Index = consecutive_failed_resets,
# capped at the last entry for anything beyond.
BACKOFF_MINUTES = [0, 5, 15, 60]

# journalctl prepends its own "Aug 21 15:39:02 mrteeny python3[449716]: "
# prefix before the app's own line -- "2026-08-21 15:39:02,568 WARNING
# Collector health: stuck" -- so this deliberately doesn't anchor to the
# start of the line, just finds the app's own timestamp + message anywhere
# in it.
_HEALTH_LINE_RE = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\w+\s+Collector health: (?P<status>\w+)")


class JournalUnavailable(Exception):
    """`journalctl` couldn't be read (systemd down, unit missing, etc.)."""


def fetch_recent_health_lines(unit: str, since_minutes: int, *, timeout: float = 30.0) -> list[str]:
    try:
        result = subprocess.run(
            ["journalctl", "-u", unit, "--since", f"{since_minutes} min ago", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise JournalUnavailable(f"journalctl -u {unit}: {err}") from err
    if result.returncode != 0:
        raise JournalUnavailable(f"journalctl -u {unit} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.splitlines()


def current_status(lines: list[str]) -> str | None:
    """The status from the most recent "Collector health: X" line, or None
    if there isn't one in the given lines at all."""
    latest: tuple[datetime, str] | None = None
    for line in lines:
        m = _HEALTH_LINE_RE.search(line)
        if not m:
            continue
        try:
            at = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if latest is None or at >= latest[0]:
            latest = (at, m.group("status"))
    return latest[1] if latest else None


def load_state(path: Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return {"last_reset_at": data.get("last_reset_at"), "consecutive_failed_resets": data.get("consecutive_failed_resets", 0)}
    except (OSError, json.JSONDecodeError):
        # Missing or corrupt -- treat as fresh state rather than crashing,
        # same gap-handling convention used throughout this project.
        return {"last_reset_at": None, "consecutive_failed_resets": 0}


def save_state(path: Path, state: dict) -> None:
    with open(path, "w") as f:
        json.dump(state, f)


def should_reset(state: dict, now: datetime) -> bool:
    last_reset_at = state.get("last_reset_at")
    if last_reset_at is None:
        return True
    failures = state.get("consecutive_failed_resets", 0)
    tier_index = min(failures, len(BACKOFF_MINUTES) - 1)
    cooldown = timedelta(minutes=BACKOFF_MINUTES[tier_index])
    elapsed = now - datetime.fromisoformat(last_reset_at)
    return elapsed >= cooldown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-minutes", type=int, default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)

    try:
        lines = fetch_recent_health_lines(SYSTEMD_UNIT, args.lookback_minutes)
    except JournalUnavailable as err:
        print(f"ble_auto_reset: {err}", file=sys.stderr)
        return 1

    status = current_status(lines)
    state = load_state(args.state_path)
    now = datetime.now()

    if status != STUCK:
        if state["consecutive_failed_resets"] != 0:
            state["consecutive_failed_resets"] = 0
            save_state(args.state_path, state)
            print(f"Collector health is {status!r} -- clearing failed-reset count")
        return 0

    if not should_reset(state, now):
        return 0

    print("Collector health is 'stuck' -- running ble_nightly_reset.sh")
    subprocess.run([str(RESET_SCRIPT)], check=False)
    state["last_reset_at"] = now.isoformat()
    state["consecutive_failed_resets"] = state.get("consecutive_failed_resets", 0) + 1
    save_state(args.state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
