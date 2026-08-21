from __future__ import annotations

from datetime import datetime
import subprocess
from unittest.mock import patch

from automation_health.exporter import render_prometheus_text, write_textfile_atomically

_NOW = datetime(2026, 8, 21, 18, 0, 0)


def test_render_prometheus_text_includes_help_and_type():
    text = render_prometheus_text({"weathercloud_upload": 0}, _NOW)

    assert "# HELP home_intelligence_automation_upload_errors" in text
    assert "# TYPE home_intelligence_automation_upload_errors gauge" in text


def test_render_prometheus_text_emits_one_line_per_label_including_zero():
    counts = {"weathercloud_upload": 0, "wu_pwsweather_upload": 3, "rest_command": 5}

    text = render_prometheus_text(counts, _NOW)

    assert 'home_intelligence_automation_upload_errors{automation="weathercloud_upload"} 0' in text
    assert 'home_intelligence_automation_upload_errors{automation="wu_pwsweather_upload"} 3' in text
    assert 'home_intelligence_automation_upload_errors{automation="rest_command"} 5' in text


def test_render_prometheus_text_never_leaks_message_content():
    # Defense in depth -- render_prometheus_text only ever sees a counts
    # dict, never raw log lines, but assert the invariant holds anyway.
    text = render_prometheus_text({"weathercloud_upload": 1}, _NOW)

    assert "PASSWORD" not in text
    assert "RfSpKVKI" not in text


def test_render_prometheus_text_includes_collection_timestamp_metric():
    # Staleness detection: if collect.py stops running (or docker logs
    # keeps failing), this metric stops advancing even though the error
    # counts alone would still read as "0 errors, all healthy". Flagged by
    # the infrastructure session after wiring up the Grafana alert.
    text = render_prometheus_text({"weathercloud_upload": 0}, _NOW)

    assert "# HELP home_intelligence_automation_upload_collection_timestamp_seconds" in text
    assert "# TYPE home_intelligence_automation_upload_collection_timestamp_seconds gauge" in text
    assert f"home_intelligence_automation_upload_collection_timestamp_seconds {_NOW.timestamp()}" in text


def test_write_textfile_atomically_uses_sudo_install_with_correct_ownership():
    with patch("automation_health.exporter.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        write_textfile_atomically("content\n", "/var/lib/node_exporter/textfile_collector/automation_health.prom")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0:2] == ["sudo", "install"]
    assert "-o" in args and args[args.index("-o") + 1] == "node_exporter"
    assert "-g" in args and args[args.index("-g") + 1] == "node_exporter"
    assert "-m" in args and args[args.index("-m") + 1] == "644"
    assert args[-1] == "/var/lib/node_exporter/textfile_collector/automation_health.prom"


def test_write_textfile_atomically_cleans_up_temp_file():
    import os

    seen_tmp_path = {}

    def fake_run(cmd, **kwargs):
        seen_tmp_path["path"] = cmd[-2]  # source arg, second-to-last
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("automation_health.exporter.subprocess.run", side_effect=fake_run):
        write_textfile_atomically("content\n", "/dest/path.prom")

    assert not os.path.exists(seen_tmp_path["path"])


def test_write_textfile_atomically_cleans_up_temp_file_even_on_failure():
    import os

    seen_tmp_path = {}

    def fake_run(cmd, **kwargs):
        seen_tmp_path["path"] = cmd[-2]
        raise subprocess.CalledProcessError(1, cmd)

    with patch("automation_health.exporter.subprocess.run", side_effect=fake_run):
        try:
            write_textfile_atomically("content\n", "/dest/path.prom")
        except subprocess.CalledProcessError:
            pass

    assert not os.path.exists(seen_tmp_path["path"])
