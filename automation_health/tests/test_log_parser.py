"""Fixtures below are real lines captured from `docker logs homeassistant`
during the 2026-08-20/21 outage (see docs/automation-health.md), with ANSI
color codes already stripped -- that's docker_log.py's job (see
test_docker_log.py), not this parser's; these fixtures represent what
parse_lines actually receives in the real pipeline (collect.py)."""

from __future__ import annotations

from datetime import datetime

from automation_health.log_parser import count_errors_by_automation, parse_lines

REST_COMMAND_DNS_ERROR = (
    "2026-08-20 17:40:02.213 ERROR (MainThread) [homeassistant.components.rest_command] "
    "Error fetching data: Cannot connect to host api.weathercloud.net:443 ssl:default "
    "[Timeout while contacting DNS servers]"
)
WEATHERCLOUD_SCRIPT_ERROR = (
    "2026-08-20 17:40:02.214 ERROR (MainThread) "
    "[homeassistant.components.automation.upload_eve_weather_readings_to_weathercloud] "
    'Upload Eve Weather readings to Weathercloud: Error executing script. Error for call_service '
    'at pos 1: Client error occurred when calling resource '
    '"https://api.weathercloud.net/v01/set/wid/f32914c0232953a8/key/dedb21bfc338287a6049393eb48455a8'
    '/temp/332/hum/25/bar/10135"'
)
WEATHERCLOUD_AUTOMATION_ERROR = (
    "2026-08-20 17:40:02.220 ERROR (MainThread) "
    "[homeassistant.components.automation.upload_eve_weather_readings_to_weathercloud] "
    "Error while executing automation automation.upload_eve_weather_readings_to_weathercloud: "
    'Client error occurred when calling resource "https://api.weathercloud.net/..."'
)
WEATHERCLOUD_502_WARNING = (
    "2026-08-20 19:40:01.357 WARNING (MainThread) [homeassistant.components.rest_command] "
    "Error. Url: https://api.weathercloud.net/v01/set/.../temp/372/hum/18/bar/10139. "
    "Status code 502. Payload: None"
)
WU_PWSWEATHER_AUTOMATION_ERROR_WITH_PASSWORD = (
    "2026-08-21 14:00:01.659 ERROR (MainThread) "
    "[homeassistant.components.automation.upload_eve_weather_readings_to_wu_and_pwsweather] "
    "Upload Eve Weather readings to WU and PWSWeather: Error executing script. Error for call_service "
    'at pos 1: Client error occurred when calling resource '
    '"https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php?'
    'ID=KUTSALTL858&PASSWORD=RfSpKVKI&dateutc=2026-08-21+13:00:00&tempf=73.9&humidity=35'
    '&baromin=29.92&action=updateraw&softwaretype=home-assistant"'
)
UNRELATED_TESLA_DNS_ERROR = (
    "2026-08-20 17:45:32.297 ERROR (MainThread) [homeassistant.components.tesla_fleet] "
    "Error requesting Tesla Fleet Vehicle data: Cannot connect to host "
    "fleet-api.prd.na.vn.cloud.tesla.com:443 ssl:default [Timeout while contacting DNS servers]"
)


def test_parse_lines_strips_ansi_and_extracts_fields():
    entries = parse_lines([REST_COMMAND_DNS_ERROR])

    assert len(entries) == 1
    assert entries[0].at == datetime(2026, 8, 20, 17, 40, 2)
    assert entries[0].level == "ERROR"
    assert entries[0].logger == "homeassistant.components.rest_command"


def test_parse_lines_never_captures_the_message_body():
    # The whole reason this parser exists in this shape: WU/PWSWeather logs
    # its account password in plaintext on every failure.
    entries = parse_lines([WU_PWSWEATHER_AUTOMATION_ERROR_WITH_PASSWORD])

    assert len(entries) == 1
    entry = entries[0]
    assert not hasattr(entry, "message")
    assert "RfSpKVKI" not in repr(entry)
    assert "RfSpKVKI" not in str(entry)


def test_parse_lines_skips_unmatched_lines():
    entries = parse_lines(["", "not a log line at all", "docker container starting..."])

    assert entries == []


def test_count_errors_by_automation_attributes_watched_automations_independently():
    # One failed weathercloud run logs 3 ERROR lines across 2 loggers --
    # rest_command (1x) and the automation's own logger (2x). Both are
    # counted, as independent, non-deduplicated signals (see const.py).
    lines = [REST_COMMAND_DNS_ERROR, WEATHERCLOUD_SCRIPT_ERROR, WEATHERCLOUD_AUTOMATION_ERROR]
    now = datetime(2026, 8, 20, 18, 0, 0)

    counts = count_errors_by_automation(lines, now, lookback_minutes=30)

    assert counts["weathercloud_upload"] == 2
    assert counts["rest_command"] == 1
    assert counts["wu_pwsweather_upload"] == 0


def test_count_errors_by_automation_excludes_warning_level():
    now = datetime(2026, 8, 20, 20, 0, 0)

    counts = count_errors_by_automation([WEATHERCLOUD_502_WARNING], now, lookback_minutes=30)

    assert counts["rest_command"] == 0


def test_count_errors_by_automation_excludes_unrelated_loggers():
    now = datetime(2026, 8, 20, 18, 0, 0)

    counts = count_errors_by_automation([UNRELATED_TESLA_DNS_ERROR], now, lookback_minutes=30)

    assert all(c == 0 for c in counts.values())


def test_count_errors_by_automation_excludes_lines_outside_the_lookback_window():
    now = datetime(2026, 8, 20, 19, 0, 0)  # REST_COMMAND_DNS_ERROR is 17:40 -- 80 min earlier

    counts = count_errors_by_automation([REST_COMMAND_DNS_ERROR], now, lookback_minutes=30)

    assert counts["rest_command"] == 0


def test_count_errors_by_automation_always_includes_every_known_label():
    counts = count_errors_by_automation([], datetime(2026, 8, 20, 18, 0, 0), lookback_minutes=30)

    assert counts == {"weathercloud_upload": 0, "wu_pwsweather_upload": 0, "rest_command": 0}
