"""Fixtures below are real journalctl output -- STUCK_LINE/STALE_LINE from
the 2026-08-21 wedge, the crash-loop scenario from the 2026-08-22 incident
(see docs/govee-cigar-monitor.md for both)."""

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
    service_is_active,
    should_reset,
)

STUCK_LINE = "Aug 21 15:39:02 mrteeny python3[449716]: 2026-08-21 15:39:02,568 WARNING Collector health: stuck"
STUCK_LINE_LATER = "Aug 21 15:39:47 mrteeny python3[449716]: 2026-08-21 15:39:47,623 WARNING Collector health: stuck"
STALE_LINE = "Aug 21 15:36:17 mrteeny python3[449716]: 2026-08-21 15:36:17,201 WARNING Collector health: stale"
UNRELATED_LINE = "Aug 21 15:40:10 mrteeny python3[482758]: 2026-08-21 15:40:10,822 INFO Connected to MQTT broker"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --- current_status (generic line-parsing, independent of what collector.py
# actually produces in practice) -----------------------------------------


def test_current_status_returns_stuck_from_real_captured_lines():
    assert current_status([STUCK_LINE]) == "stuck"


def test_current_status_returns_stale():
    assert current_status([STALE_LINE]) == "stale"


def test_current_status_returns_most_recent_by_timestamp_not_by_position():
    later_stale = STALE_LINE.replace("15:36:17", "15:42:00")
    assert current_status([STUCK_LINE, later_stale]) == "stale"
    assert current_status([later_stale, STUCK_LINE]) == "stale"  # order-independent


def test_current_status_none_when_no_health_line_present():
    assert current_status([UNRELATED_LINE, ""]) is None


def test_current_status_none_on_empty_input():
    assert current_status([]) is None


# --- service_is_active -----------------------------------------------------


def test_service_is_active_true_when_systemctl_reports_active():
    with patch(
        "govee_collector.ble_auto_reset.subprocess.run", return_value=_completed(returncode=0, stdout="active\n")
    ):
        assert service_is_active("govee-collector") is True


def test_service_is_active_false_when_activating_mid_restart_loop():
    # Exactly the 2026-08-22 incident's real state: "activating (auto-restart)".
    with patch(
        "govee_collector.ble_auto_reset.subprocess.run", return_value=_completed(returncode=3, stdout="activating\n")
    ):
        assert service_is_active("govee-collector") is False


def test_service_is_active_false_when_failed():
    with patch(
        "govee_collector.ble_auto_reset.subprocess.run", return_value=_completed(returncode=3, stdout="failed\n")
    ):
        assert service_is_active("govee-collector") is False


def test_service_is_active_false_on_subprocess_error():
    # Fails safe -- an unreachable systemctl should not be read as healthy.
    with patch("govee_collector.ble_auto_reset.subprocess.run", side_effect=FileNotFoundError("no systemctl")):
        assert service_is_active("govee-collector") is False


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


FRESH_STATE = {"last_reset_at": None, "consecutive_failed_resets": 0, "rebooted_at": None, "gave_up": False}


def test_load_state_returns_fresh_state_when_file_missing(tmp_path):
    state = load_state(tmp_path / "does_not_exist.json")

    assert state == FRESH_STATE


def test_load_state_returns_fresh_state_when_file_corrupt(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not valid json{{{")

    state = load_state(path)

    assert state == FRESH_STATE


def test_load_state_round_trips(tmp_path):
    from govee_collector.ble_auto_reset import save_state

    path = tmp_path / "state.json"
    full_state = {
        "last_reset_at": "2026-08-21T16:00:00",
        "consecutive_failed_resets": 2,
        "rebooted_at": "2026-08-22T17:00:00",
        "gave_up": False,
    }
    save_state(path, full_state)

    assert load_state(path) == full_state


def test_load_state_fills_in_missing_reboot_fields_for_backward_compatibility(tmp_path):
    # A state file written by the pre-reboot-escalation version of this
    # script won't have rebooted_at/gave_up at all.
    path = tmp_path / "old_state.json"
    path.write_text(json.dumps({"last_reset_at": "2026-08-21T16:00:00", "consecutive_failed_resets": 1}))

    state = load_state(path)

    assert state["rebooted_at"] is None
    assert state["gave_up"] is False


# --- fetch_recent_health_lines -------------------------------------------


def test_fetch_recent_health_lines_runs_journalctl_with_unit_and_since():
    with patch(
        "govee_collector.ble_auto_reset.subprocess.run", return_value=_completed(stdout="a line\n")
    ) as mock_run:
        fetch_recent_health_lines("govee-collector", since_minutes=5)

    args = mock_run.call_args[0][0]
    assert args == ["journalctl", "-u", "govee-collector", "--since", "5 min ago", "--no-pager"]


def test_fetch_recent_health_lines_raises_on_nonzero_exit():
    with patch(
        "govee_collector.ble_auto_reset.subprocess.run",
        return_value=_completed(returncode=1, stderr="No such unit"),
    ):
        with pytest.raises(JournalUnavailable):
            fetch_recent_health_lines("govee-collector", since_minutes=5)


def test_fetch_recent_health_lines_raises_on_subprocess_error():
    with patch("govee_collector.ble_auto_reset.subprocess.run", side_effect=FileNotFoundError("no journalctl")):
        with pytest.raises(JournalUnavailable):
            fetch_recent_health_lines("govee-collector", since_minutes=5)


# --- main() wiring ---------------------------------------------------------


def _run_main(state_path, health_lines, service_active, **extra_argv):
    with (
        patch("govee_collector.ble_auto_reset.fetch_recent_health_lines", return_value=health_lines),
        patch("govee_collector.ble_auto_reset.service_is_active", return_value=service_active),
        patch("govee_collector.ble_auto_reset.subprocess.run") as mock_run,
    ):
        rc = main(["--state-path", str(state_path)])
    return rc, mock_run


def test_main_does_nothing_when_no_health_line_and_service_active(tmp_path):
    # The real "everything's fine" case: collector.py never logs an
    # explicit "ok" line, so this is what genuine health looks like.
    rc, mock_run = _run_main(tmp_path / "state.json", [UNRELATED_LINE], service_active=True)

    assert rc == 0
    mock_run.assert_not_called()


def test_main_clears_failure_count_when_no_health_line_and_service_active(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_reset_at": "2026-08-21T15:00:00", "consecutive_failed_resets": 2}))

    rc, mock_run = _run_main(state_path, [], service_active=True)

    mock_run.assert_not_called()
    assert json.loads(state_path.read_text())["consecutive_failed_resets"] == 0


def test_main_resets_when_no_health_line_and_service_not_active(tmp_path):
    # The actual 2026-08-22 bug: a crash-looping collector produces zero
    # "Collector health: X" lines (it dies before reaching that code), and
    # the old version of this script treated that as healthy. It must now
    # be treated at least as seriously as "stuck".
    state_path = tmp_path / "state.json"

    rc, mock_run = _run_main(state_path, [], service_active=False)

    assert rc == 0
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0].endswith("ble_nightly_reset.sh")

    saved = json.loads(state_path.read_text())
    assert saved["consecutive_failed_resets"] == 1
    assert saved["last_reset_at"] is not None


def test_main_does_nothing_for_stale_status_regardless_of_service_state(tmp_path):
    # collector.py's own watchdog is still within its retry budget --
    # an external reset shouldn't preempt it.
    rc, mock_run = _run_main(tmp_path / "state.json", [STALE_LINE], service_active=True)

    assert rc == 0
    mock_run.assert_not_called()


def test_main_runs_reset_script_when_stuck_and_never_reset_before(tmp_path):
    state_path = tmp_path / "state.json"

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

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

    rc, mock_run = _run_main(state_path, [STUCK_LINE_LATER], service_active=True)

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


# --- reboot escalation (2026-08-22 incident #2: hciconfig alone can't fix
# a kernel-level lockup; only a reboot did, live) -------------------------


def test_main_reboots_after_enough_failed_resets(tmp_path):
    from govee_collector.ble_auto_reset import REBOOT_AFTER_CONSECUTIVE_FAILURES

    state_path = tmp_path / "state.json"
    long_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_reset_at": long_ago,
                "consecutive_failed_resets": REBOOT_AFTER_CONSECUTIVE_FAILURES,
                "rebooted_at": None,
                "gave_up": False,
            }
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    assert rc == 0
    mock_run.assert_called_once_with(["sudo", "reboot"], check=False)

    saved = json.loads(state_path.read_text())
    assert saved["rebooted_at"] is not None
    # Not touched by the reboot branch -- last_reset_at still reflects the
    # last hciconfig-based attempt, not the reboot.
    assert saved["last_reset_at"] == long_ago


def test_main_does_not_reboot_before_enough_failed_resets(tmp_path):
    from govee_collector.ble_auto_reset import REBOOT_AFTER_CONSECUTIVE_FAILURES

    state_path = tmp_path / "state.json"
    long_ago = (datetime.now() - timedelta(hours=2)).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_reset_at": long_ago,
                "consecutive_failed_resets": REBOOT_AFTER_CONSECUTIVE_FAILURES - 1,
                "rebooted_at": None,
                "gave_up": False,
            }
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0].endswith("ble_nightly_reset.sh")  # still the plain reset, not a reboot yet


def test_main_waits_within_the_post_reboot_grace_period(tmp_path):
    state_path = tmp_path / "state.json"
    recent_reboot = (datetime.now() - timedelta(minutes=3)).isoformat()
    state_path.write_text(
        json.dumps(
            {"last_reset_at": None, "consecutive_failed_resets": 3, "rebooted_at": recent_reboot, "gave_up": False}
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    assert rc == 0
    mock_run.assert_not_called()
    saved = json.loads(state_path.read_text())
    assert saved["gave_up"] is False
    assert saved["rebooted_at"] == recent_reboot


def test_main_gives_up_when_still_broken_past_the_grace_period(tmp_path, capsys):
    from govee_collector.ble_auto_reset import REBOOT_GRACE_PERIOD_MINUTES

    state_path = tmp_path / "state.json"
    old_reboot = (datetime.now() - timedelta(minutes=REBOOT_GRACE_PERIOD_MINUTES + 1)).isoformat()
    state_path.write_text(
        json.dumps(
            {"last_reset_at": None, "consecutive_failed_resets": 3, "rebooted_at": old_reboot, "gave_up": False}
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    assert rc == 1
    mock_run.assert_not_called()  # no further action taken -- just gives up
    assert "giving up" in capsys.readouterr().err.lower()
    assert json.loads(state_path.read_text())["gave_up"] is True


def test_main_gives_up_exactly_at_the_grace_period_boundary(tmp_path):
    from govee_collector.ble_auto_reset import REBOOT_GRACE_PERIOD_MINUTES

    state_path = tmp_path / "state.json"
    exactly_at_boundary = (datetime.now() - timedelta(minutes=REBOOT_GRACE_PERIOD_MINUTES)).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_reset_at": None,
                "consecutive_failed_resets": 3,
                "rebooted_at": exactly_at_boundary,
                "gave_up": False,
            }
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    assert rc == 1
    assert json.loads(state_path.read_text())["gave_up"] is True


def test_main_stays_given_up_on_subsequent_runs_without_rechecking_timing(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_reset_at": None,
                "consecutive_failed_resets": 3,
                "rebooted_at": datetime.now().isoformat(),  # recent -- would normally still be in grace period
                "gave_up": True,
            }
        )
    )

    rc, mock_run = _run_main(state_path, [STUCK_LINE], service_active=True)

    assert rc == 1
    mock_run.assert_not_called()


def test_main_recovery_clears_reboot_and_give_up_state_too(tmp_path):
    # Recovery must reset the *entire* incident's state, not just the
    # hciconfig-based failure count -- otherwise a fresh future incident
    # would inherit a stale gave_up=True and never even attempt a reset.
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_reset_at": "2026-08-22T15:00:00",
                "consecutive_failed_resets": 3,
                "rebooted_at": "2026-08-22T16:00:00",
                "gave_up": True,
            }
        )
    )

    rc, mock_run = _run_main(state_path, [], service_active=True)  # no health line + active = healthy

    assert rc == 0
    mock_run.assert_not_called()
    assert json.loads(state_path.read_text()) == FRESH_STATE
