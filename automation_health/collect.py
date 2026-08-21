#!/usr/bin/env python3
"""CLI entry point: counts recent HA automation/rest_command errors and
writes a Prometheus textfile-collector metric.

Meant to run every 10 minutes via cron -- one `docker logs` call plus
regex parsing, cheap enough for that cadence and matches the tightest
watched automation's own trigger interval.

On a docker-logs failure, deliberately leaves the previous `.prom` file in
place rather than writing a "0 errors" metric that would read as healthy
when the check itself just failed to run.
"""

from __future__ import annotations

import argparse
import datetime as dt_module
import sys

from automation_health.const import DEFAULT_LOOKBACK_MINUTES, DOCKER_CONTAINER, TEXTFILE_COLLECTOR_PATH
from automation_health.docker_log import DockerLogUnavailable, fetch_recent_log_lines
from automation_health.exporter import render_prometheus_text, write_textfile_atomically
from automation_health.log_parser import count_errors_by_automation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-minutes", type=int, default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument("--textfile-path", default=TEXTFILE_COLLECTOR_PATH)
    args = parser.parse_args(argv)

    try:
        lines = fetch_recent_log_lines(DOCKER_CONTAINER, args.lookback_minutes)
    except DockerLogUnavailable as err:
        print(f"automation_health: {err} -- leaving previous metric file untouched", file=sys.stderr)
        return 1

    now = dt_module.datetime.now()
    counts = count_errors_by_automation(lines, now, args.lookback_minutes)
    content = render_prometheus_text(counts, now)
    write_textfile_atomically(content, args.textfile_path)
    print(f"Wrote {args.textfile_path}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
