"""Fixed config for the automation-health exporter.

Watches the two weather-upload automations that went silently dark for
~10 hours on 2026-08-20/21 (see docs/automation-health.md) -- not the HA
REST API (its `/api/error_log` endpoint 404s on this install), but
`docker logs homeassistant`, which jramsey can already read without sudo.
"""

from __future__ import annotations

DOCKER_CONTAINER = "homeassistant"

DEFAULT_LOOKBACK_MINUTES = 30

# node_exporter's textfile collector -- owned by node_exporter:node_exporter,
# not jramsey, so writing here goes through `sudo install` (see exporter.py)
# rather than a direct write or a directory permission change.
TEXTFILE_COLLECTOR_PATH = "/var/lib/node_exporter/textfile_collector/automation_health.prom"
TEXTFILE_OWNER = "node_exporter"
TEXTFILE_GROUP = "node_exporter"

# Maps a fragment of the HA automation logger name
# (homeassistant.components.automation.<this>) to the short label used in
# the exported metric. A failed automation run logs ERROR lines on *two*
# distinct loggers -- its own (homeassistant.components.automation.<x>,
# fired twice per failed run: "Error executing script" + "Error while
# executing automation") and the generic
# homeassistant.components.rest_command ("Error fetching data", fired once
# per failed HTTP call, from *any* rest_command, watched or not). These are
# counted as two independent labels rather than deduplicated into one
# "number of failures" -- see log_parser.py's count_errors_by_automation().
WATCHED_AUTOMATIONS: dict[str, str] = {
    "upload_eve_weather_readings_to_weathercloud": "weathercloud_upload",
    "upload_eve_weather_readings_to_wu_and_pwsweather": "wu_pwsweather_upload",
}

REST_COMMAND_LOGGER = "homeassistant.components.rest_command"
REST_COMMAND_LABEL = "rest_command"

METRIC_NAME = "home_intelligence_automation_upload_errors"

# A metric that only reports counts reads as "0 errors, all healthy" if the
# collector itself silently stops running -- this tracks when collect.py
# last *actually completed* a collection (docker logs fetch + parse +
# write all succeeded), so staleness (the cron job died, docker logs kept
# failing, etc.) can be alerted on independently of the error counts
# themselves. Flagged by the infrastructure session after wiring up the
# Grafana alert -- same failure shape they'd separately hit with a
# speedtest metric that week.
COLLECTION_TIMESTAMP_METRIC_NAME = "home_intelligence_automation_upload_collection_timestamp_seconds"
