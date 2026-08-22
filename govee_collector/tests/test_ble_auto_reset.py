"""Fixtures below are the real journalctl output captured during today's
(2026-08-21) live BLE wedge -- see docs/govee-cigar-monitor.md."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import subprocess
from unittest.mock import patch

import pytest

from govee_collector.ble_auto_reset import (
    JournalUnavailable,
    current_status,
    fetch_recent_health_lines,
    load_state,
    main,
    should_reset,
)

STUCK_LINE = "Aug 21 15:39:02 mrteeny python3[449716]: 2026-08-21 15:39:02,568 WARNING Collector health: stuck"
STUCK_LINE_LATER = "Aug 21 15:39:47 mrteeny python3[449716]: 2026-08-21 15:39:47,623 WARNING Collector health: stuck"
OK_LINE = "Aug 21 15:40:10 mrteeny python3[482758]: 2026-08-21 15:40:10,700 INFO Collector health: ok"
UNRELATED_LINE = "Aug 21 15:40:10 mrteeny python3[482758]: 2026-08-21 15:40:10,822 INFO Connected to MQTT broker"


# --- current_status ---------------------------------------------------


def test_current_status_returns_stuck_from_real_captured_lines():
    assert current_status([STUCK_LINE]) == "stuck"


def test_current_status_returns_most_recent_by_timestamp_not_by_position():
    # OK_LINE is later than STUCK_LINE -- a recovered collector shouldn't
    # keep reading as stuck just because an older stuck line is also
    # present in the lookback window.
    assert current_status([STUCK_LINE, OK_LINE]) == "ok"
    assert current_status([OK_LINE, STUCK_LINE]) == "ok"  # order-independent


def test_current_status_none_when_no_health_line_present():
    assert current_status([UNRELATED_LINE, ""]) is None


def test_current_status_none_on_empty_input():
    assert current_status([]) is None


# --- should_reset (tiered backoff, table-driven) -----------------------


@pytest.mark.parametrize(
    "failures,minutes_since_last_reset,expected",
    [
        (0, 0, True),  # never reset before -- handled by last_reset_at is None, not this table
        (0, 4, True),  # tier 0: immediate
        (1, 4, False),  # tier 1: < 5 min, still cooling down
        (1, 5, True),  # tier 1: exactly 5 min
        (2, 14, False),  # tier 2: < 15 min
        (2, 15, True),  # tier 2: exactly 15 min
        (3, 59, False),  # tier 3+: < 60 min
        (3, 60, True),  # tier 3+: exactly 60 min
        (10, 59, False),  # beyond the table -- capped at the last tier
        (10, 60, True),
    ],
)
def test_should_reset_tiered_backoff(failures, minutes_since_last_reset, expected):
    now = datetime(2026, 8, 21, 16, 0, 0)
    last_reset_at = now - timedelta(minutes=minutes_since_last_reset)
    state = {"last_reset_at": last_reset_at.isoformat(), "consecutive_failed_resets": failures}

    assert should_reset(state, now) is expected


def test_should_reset_true_when_never_reset_before():
    state = {"last_reset_at": None, "consecutive_failed_resets": 0}

    assert should_reset(state, datetime(2026, 8, 21, 16, 0, 0)) is True


# --- load_state ----------------------------------------------------------


def test_load_state_returns_fresh_state_when_file_missing(tmp_path):
    state = load_state(tmp_path / "does_not_exist.json")

    assert state == {"last_reset_at": None, "consecutive_failed_resets": 0}


def test_load_state_returns_fresh_state_when_file_corrupt(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not valid json{{{")

    state = load_state(path)

    assert state == {"last_reset_at": None, "consecutive_failed_resets": 0}


def test_load_state_round_trips(tmp_path):
    from govee_collector.ble_auto_reset import save_state

    path = tmp_path / "state.json"
    save_state(path, {"last_reset_at": "2026-08-21T16:00:00", "consecutive_failed_resets": 2})

    assert load_state(path) == {"last_reset_at": "2026-08-21T16:00:00", "consecutive_failed_resets": 2}


# --- fetch_recent_health_lines -------------------------------------------


def test_fetch_recent_health_lines_runs_journalctl_with_unit_and_since():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="a line\n", stderr="")
    with patch("govee_collector.ble_auto_reset.subprocess.run", return_value=completed) as mock_run:
        fetch_recent_health_lines("govee-collector", since_minutes=5)

    args = mock_run.call_args[0][0]
    assert args == ["journalctl", "-u", "govee-collector", "--since", "5 min ago", "--no-pager"]


def test_fetch_recent_health_lines_raises_on_nonzero_exit():
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="No such unit")
    with patch("govee_collector.ble_auto_reset.subprocess.run", return_value=completed):
        with pytest.raises(JournalUnavailable):
            fetch_recent_health_lines("govee-collector", since_minutes=5)


def test_fetch_recent_health_lines_raises_on_subprocess_error():
    with patch("govee_collector.ble_auto_reset.subprocess.run", side_effect=FileNotFoundError("no journalctl")):
        with pytest.raises(JournalUnavailable):
            fetch_recent_health_lines("govee-collector", since_minutes=5)


# --- main() wiring ---------------------------------------------------------


def test_main_does_nothing_when_healthy(tmp_path, capsys):
    state_path = tmp_path / "state.json"

    with (
        patch("govee_collector.ble_auto_reset.fetch_recent_health_lines", return_value=[OK_LINE]),
        patch("govee_collector.ble_auto_reset.subprocess.run") as mock_run,
    ):
        rc = main(["--state-path", str(state_path)])

    assert rc == 0
    mock_run.assert_not_called()


def test_main_clears_failure_count_once_healthy_again(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_reset_at": "2026-08-21T15:00:00", "consecutive_failed_resets": 2}))

    with (
        patch("govee_collector.ble_auto_reset.fetch_recent_health_lines", return_value=[OK_LINE]),
        patch("govee_collector.ble_auto_reset.subprocess.run") as mock_run,
    ):
        main(["--state-path", str(state_path)])

    mock_run.assert_not_called()
    assert json.loads(state_path.read_text())["consecutive_failed_resets"] == 0


def test_main_runs_reset_script_when_stuck_and_never_reset_before(tmp_path):
    state_path = tmp_path / "state.json"

    with (
        patch("govee_collector.ble_auto_reset.fetch_recent_health_lines", return_value=[STUCK_LINE]),
        patch("govee_collector.ble_auto_reset.subprocess.run") as mock_run,
    ):
        rc = main(["--state-path", str(state_path)])

    assert rc == 0
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0].endswith("ble_nightly_reset.sh")

    saved = json.loads(state_path.read_text())
    assert saved["consecutive_failed_resets"] == 1
    assert saved["last_reset_at"] is not None


def test_main_skips_reset_when_still_in_cooldown(tmp_path):
    state_path = tmp_path / "state.json"
    recent = datetime.now().isoformat()
    state_path.write_text(json.dumps({"last_reset_at": recent, "consecutive_failed_resets": 1}))

    with (
        patch("govee_collector.ble_auto_reset.fetch_recent_health_lines", return_value=[STUCK_LINE_LATER]),
        patch("govee_collector.ble_auto_reset.subprocess.run") as mock_run,
    ):
        main(["--state-path", str(state_path)])

    mock_run.assert_not_called()


def test_main_returns_1_and_leaves_state_untouched_on_journal_failure(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_reset_at": None, "consecutive_failed_resets": 0}))

    with patch(
        "govee_collector.ble_auto_reset.fetch_recent_health_lines", side_effect=JournalUnavailable("no journal")
    ):
        rc = main(["--state-path", str(state_path)])

    assert rc == 1
    assert "no journal" in capsys.readouterr().err
    assert json.loads(state_path.read_text())["consecutive_failed_resets"] == 0
