"""Parses HA's log lines into (timestamp, level, logger) only.

Deliberately never captures or returns the message body: the WU/PWSWeather
rest_command logs its account password in plaintext on every failure (a
pre-existing HA-side issue, unrelated to this package), so nothing here
ever touches the text after the `[logger]` prefix, and nothing downstream
(exporter.py's Prometheus output, cron.log) can leak it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from automation_health.const import REST_COMMAND_LABEL, REST_COMMAND_LOGGER, WATCHED_AUTOMATIONS

# "2026-08-20 17:40:02.213 ERROR (MainThread) [homeassistant.components.rest_command] <message we never capture>"
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\s+"
    r"(?P<level>[A-Z]+)\s+\([^)]*\)\s+\[(?P<logger>[^\]]+)\]"
)

_AUTOMATION_LOGGERS = {f"homeassistant.components.automation.{fragment}": label for fragment, label in WATCHED_AUTOMATIONS.items()}


@dataclass(frozen=True)
class LogEntry:
    at: datetime
    level: str
    logger: str


def parse_lines(lines: list[str]) -> list[LogEntry]:
    entries = []
    for line in lines:
        m = _LINE_RE.match(line)
        if not m:
            continue
        try:
            at = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        entries.append(LogEntry(at=at, level=m.group("level"), logger=m.group("logger")))
    return entries


def _label_for_logger(logger: str) -> str | None:
    """None if this logger isn't one we count -- most HA log lines aren't."""
    if logger == REST_COMMAND_LOGGER:
        return REST_COMMAND_LABEL
    return _AUTOMATION_LOGGERS.get(logger)


def count_errors_by_automation(lines: list[str], now: datetime, lookback_minutes: int) -> dict[str, int]:
    """ERROR-level counts within the lookback window, keyed by label.
    Always includes every known label at 0 if nothing matched, so a
    healthy window still emits the full label set (see exporter.py)."""
    counts = {label: 0 for label in list(WATCHED_AUTOMATIONS.values()) + [REST_COMMAND_LABEL]}
    cutoff = now - timedelta(minutes=lookback_minutes)
    for entry in parse_lines(lines):
        if entry.level != "ERROR" or entry.at < cutoff:
            continue
        label = _label_for_logger(entry.logger)
        if label is not None:
            counts[label] += 1
    return counts
