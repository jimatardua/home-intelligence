from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from automation_health.docker_log import DockerLogUnavailable, fetch_recent_log_lines


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_fetch_recent_log_lines_runs_docker_logs_with_since():
    with patch("automation_health.docker_log.subprocess.run", return_value=_completed(stdout="a line\n")) as mock_run:
        fetch_recent_log_lines("homeassistant", since_minutes=30)

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["docker", "logs", "homeassistant", "--since", "30m"]


def test_fetch_recent_log_lines_strips_ansi_codes():
    raw = "\x1b[31m2026-08-20 17:40:02.213 ERROR (MainThread) [x] msg\x1b[0m\n"
    with patch("automation_health.docker_log.subprocess.run", return_value=_completed(stdout=raw)):
        lines = fetch_recent_log_lines("homeassistant", since_minutes=30)

    assert lines == ["2026-08-20 17:40:02.213 ERROR (MainThread) [x] msg"]


def test_fetch_recent_log_lines_combines_stdout_and_stderr():
    with patch(
        "automation_health.docker_log.subprocess.run",
        return_value=_completed(stdout="out line\n", stderr="err line\n"),
    ):
        lines = fetch_recent_log_lines("homeassistant", since_minutes=30)

    assert lines == ["out line", "err line"]


def test_fetch_recent_log_lines_raises_on_nonzero_exit():
    with patch(
        "automation_health.docker_log.subprocess.run",
        return_value=_completed(returncode=1, stderr="No such container: homeassistant"),
    ):
        with pytest.raises(DockerLogUnavailable):
            fetch_recent_log_lines("homeassistant", since_minutes=30)


def test_fetch_recent_log_lines_raises_on_subprocess_error():
    with patch("automation_health.docker_log.subprocess.run", side_effect=FileNotFoundError("no docker binary")):
        with pytest.raises(DockerLogUnavailable):
            fetch_recent_log_lines("homeassistant", since_minutes=30)


def test_fetch_recent_log_lines_raises_on_timeout():
    with patch(
        "automation_health.docker_log.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=30),
    ):
        with pytest.raises(DockerLogUnavailable):
            fetch_recent_log_lines("homeassistant", since_minutes=30)
