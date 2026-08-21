from __future__ import annotations

from unittest.mock import patch

from automation_health.collect import main
from automation_health.docker_log import DockerLogUnavailable


def test_main_writes_metric_on_success(capsys):
    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]) as mock_fetch,
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        rc = main(["--lookback-minutes", "15", "--textfile-path", "/tmp/x.prom"])

    assert rc == 0
    mock_fetch.assert_called_once_with("homeassistant", 15)
    mock_write.assert_called_once()
    content_arg, path_arg = mock_write.call_args[0]
    assert path_arg == "/tmp/x.prom"
    assert "home_intelligence_automation_upload_errors" in content_arg


def test_main_leaves_previous_file_untouched_on_docker_log_failure(capsys):
    with (
        patch("automation_health.collect.fetch_recent_log_lines", side_effect=DockerLogUnavailable("no daemon")),
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        rc = main([])

    assert rc == 1
    mock_write.assert_not_called()
    assert "no daemon" in capsys.readouterr().err


def test_main_uses_default_lookback_and_path_when_not_overridden():
    from automation_health.const import DEFAULT_LOOKBACK_MINUTES, TEXTFILE_COLLECTOR_PATH

    with (
        patch("automation_health.collect.fetch_recent_log_lines", return_value=[]) as mock_fetch,
        patch("automation_health.collect.write_textfile_atomically") as mock_write,
    ):
        main([])

    mock_fetch.assert_called_once_with("homeassistant", DEFAULT_LOOKBACK_MINUTES)
    assert mock_write.call_args[0][1] == TEXTFILE_COLLECTOR_PATH
