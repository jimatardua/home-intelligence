"""Renders and installs the Prometheus textfile-collector metric.

`/var/lib/node_exporter/textfile_collector/` is owned by
node_exporter:node_exporter, not jramsey (confirmed live -- a direct write
gets Permission denied). jramsey already has passwordless sudo for
everything on domus, pre-existing and not something this package grants --
used narrowly here via `sudo install` to place one file, rather than
loosening the directory's own ownership.
"""

from __future__ import annotations

from datetime import datetime
import os
import subprocess
import tempfile

from automation_health.const import COLLECTION_TIMESTAMP_METRIC_NAME, METRIC_NAME, TEXTFILE_GROUP, TEXTFILE_OWNER

_HELP = (
    f"# HELP {METRIC_NAME} Count of ERROR-level Home Assistant log lines "
    "in the lookback window (docker logs homeassistant), per logger -- "
    "NOT deduplicated per failed run. See automation_health/log_parser.py."
)
_TYPE = f"# TYPE {METRIC_NAME} gauge"

_COLLECTION_HELP = (
    f"# HELP {COLLECTION_TIMESTAMP_METRIC_NAME} Unix timestamp of the last "
    "time this exporter successfully completed a collection. Use for "
    "staleness alerting -- if this stops advancing, automation_health has "
    "stopped checking, which reads identically to \"all clear\" in the "
    "error-count metric alone."
)
_COLLECTION_TYPE = f"# TYPE {COLLECTION_TIMESTAMP_METRIC_NAME} gauge"


def render_prometheus_text(counts: dict[str, int], collected_at: datetime) -> str:
    lines = [_HELP, _TYPE]
    for label, count in counts.items():
        lines.append(f'{METRIC_NAME}{{automation="{label}"}} {count}')
    lines += [_COLLECTION_HELP, _COLLECTION_TYPE, f"{COLLECTION_TIMESTAMP_METRIC_NAME} {collected_at.timestamp()}"]
    return "\n".join(lines) + "\n"


def write_textfile_atomically(content: str, dest_path: str) -> None:
    """Writes to a jramsey-owned temp file, then `sudo install`s it into
    place -- `install` copies and atomically renames in one step, matching
    node_exporter's documented safe-write contract (a scraper never reads a
    half-written file)."""
    fd, tmp_path = tempfile.mkstemp(prefix="automation_health_", suffix=".prom")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        subprocess.run(
            ["sudo", "install", "-o", TEXTFILE_OWNER, "-g", TEXTFILE_GROUP, "-m", "644", tmp_path, dest_path],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
