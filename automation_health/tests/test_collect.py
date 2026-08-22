from __future__ import annotations

import json
from unittest.mock import patch

from automation_health.collect import load_state, main, save_state
from automation_health.const import DEFAULT_LOOKBACK_MINUTES, TEXTFILE_COLLECTOR_PATH
from automation_health.docker_log import DockerLogUnavailable


def test_main_writes_metric_on_success(tmp_path):
    state_path = tmp_path / "state.json"

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]) as mock_fetch,
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        rc = main(["--textfile-path", "/tmp/x.prom", "--state-path", str(state_path)])

    assert rc == 0
    mock_fetch.assert_called_once()
    mock_write.assert_called_once()
    content_arg, path_arg = mock_write.call_args[0]
    assert path_arg == "/tmp/x.prom"
    assert "home_intelligence_automation_upload_errors" in content_arg


def test_main_first_run_falls_back_to_default_lookback(tmp_path):
    # No prior state -- nothing to compute a delta window from yet.
    state_path = tmp_path / "state.json"

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]) as mock_fetch,
        patch("automation_health.collect.write_textfile_atomically"),
    ):
        main(["--state-path", str(state_path)])

    args = mock_fetch.call_args[0]
    assert args[0] == "homeassistant"
    assert args[1] >= DEFAULT_LOOKBACK_MINUTES


def test_main_subsequent_run_uses_delta_since_last_success(tmp_path):
    state_path = tmp_path / "state.json"
    import datetime as dt_module

    last_run = dt_module.datetime.now() - dt_module.timedelta(minutes=6)
    state_path.write_text(json.dumps({"last_collected_at": last_run.isoformat()}))

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]) as mock_fetch,
        patch("automation_health.collect.write_textfile_atomically"),
    ):
        main(["--state-path", str(state_path)])

    lookback_minutes_arg = mock_fetch.call_args[0][1]
    # ~6 minutes since last run + a couple minutes margin -- nowhere near
    # the old 30-minute sliding window.
    assert 6 <= lookback_minutes_arg <= 10


def test_main_saves_last_collected_at_on_success(tmp_path):
    state_path = tmp_path / "state.json"

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]),
        patch("automation_health.collect.write_textfile_atomically"),
    ):
        main(["--state-path", str(state_path)])

    saved = json.loads(state_path.read_text())
    assert saved["last_collected_at"] is not None


def test_main_leaves_previous_file_untouched_on_docker_log_failure(tmp_path, capsys):
    state_path = tmp_path / "state.json"

    with (
        patch("automation_health.collect.fetch_recent_log_lines", side_effect=DockerLogUnavailable("no daemon")),
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        rc = main(["--state-path", str(state_path)])

    assert rc == 1
    mock_write.assert_not_called()
    assert "no daemon" in capsys.readouterr().err


def test_main_does_not_advance_state_on_docker_log_failure(tmp_path):
    # A failed run's window should get picked up by the *next* successful
    # run instead of silently vanishing -- see collect.py's docstring.
    state_path = tmp_path / "state.json"
    import datetime as dt_module

    original = dt_module.datetime(2026, 8, 21, 12, 0, 0).isoformat()
    state_path.write_text(json.dumps({"last_collected_at": original}))

    with patch("automation_health.collect.fetch_recent_log_lines", side_effect=DockerLogUnavailable("x")):
        main(["--state-path", str(state_path)])

    assert json.loads(state_path.read_text())["last_collected_at"] == original


def test_main_uses_default_path_when_not_overridden(tmp_path):
    state_path = tmp_path / "state.json"

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]),
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        main(["--state-path", str(state_path)])

    assert mock_write.call_args[0][1] == TEXTFILE_COLLECTOR_PATH


# --- load_state / save_state ----------------------------------------------


def test_load_state_returns_fresh_state_when_file_missing(tmp_path):
    assert load_state(tmp_path / "missing.json") == {"last_collected_at": None}


def test_load_state_returns_fresh_state_when_file_corrupt(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not json{{{")

    assert load_state(path) == {"last_collected_at": None}


def test_load_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"last_collected_at": "2026-08-21T12:00:00"})

    assert load_state(path) == {"last_collected_at": "2026-08-21T12:00:00"}
