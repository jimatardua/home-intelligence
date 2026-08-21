"""Fetches recent log lines from the `homeassistant` container.

HA's own `/api/error_log` REST endpoint 404s on this install (confirmed
live), so `docker logs` is the actual data source -- jramsey can already
read it without sudo (in the `docker` group).
"""

from __future__ import annotations

import re
import subprocess

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class DockerLogUnavailable(Exception):
    """`docker logs` couldn't be read (daemon down, container missing, etc.)."""


def fetch_recent_log_lines(container: str, since_minutes: int, *, timeout: float = 30.0) -> list[str]:
    """Every line the container has logged in the last `since_minutes`,
    ANSI color codes stripped. Docker splits a container's stdout/stderr
    into its own stdout/stderr -- HA's log lines showed up needing `2>&1`
    when checked manually, so both are captured and combined here."""
    try:
        result = subprocess.run(
            ["docker", "logs", container, "--since", f"{since_minutes}m"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise DockerLogUnavailable(f"docker logs {container}: {err}") from err
    if result.returncode != 0:
        raise DockerLogUnavailable(f"docker logs {container} exited {result.returncode}: {result.stderr.strip()}")
    combined = result.stdout + result.stderr
    return [_ANSI_RE.sub("", line) for line in combined.splitlines()]
