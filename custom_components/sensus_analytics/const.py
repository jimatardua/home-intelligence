"""Constants for the Sensus Analytics integration.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md and docs/sensus-analytics-water.md for what changed and
why.
"""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "sensus_analytics"
LOGGER = logging.getLogger(__package__)

# CONF_USERNAME/CONF_PASSWORD are imported from homeassistant.const
# instead of redefined here (the fork's original const.py duplicated
# them) -- same convention custom_components/rocky_mountain_power already
# uses in this repo. Their string values ("username"/"password") are
# unchanged, so existing config entry data is unaffected.
CONF_BASE_URL = "base_url"
CONF_ACCOUNT_NUMBER = "account_number"
CONF_METER_NUMBER = "meter_number"

DEFAULT_NAME = "Sensus Analytics"

# --- Endpoints (relative to CONF_BASE_URL, e.g. https://my-slc.sensus-analytics.com/) ---
LOGIN_PATH = "j_spring_security_check"
DAILY_WIDGET_PATH = "water/widget/byPage"
HOURLY_USAGE_PATH_TEMPLATE = "water/usage/{account_number}/{meter_number}"

# --- Behavior ---
# Sensus Analytics is documented (by the HA community thread that first
# reverse-engineered this API) to update anywhere from once daily to every
# few hours depending on the utility -- SLC's own cadence is unconfirmed
# as of this writing (blocked on live credentials, see
# docs/sensus-analytics-water.md). 30 minutes is a conservative default;
# tune once real update timestamps have been observed against the actual
# my-slc.sensus-analytics.com data. The original fork polled every 5
# minutes, which is harmless but pointless against data that changes this
# infrequently.
UPDATE_INTERVAL = timedelta(minutes=30)

REQUEST_TIMEOUT_SECONDS = 10
