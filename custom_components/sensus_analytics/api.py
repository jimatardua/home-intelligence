"""Synchronous client for the Sensus Analytics customer portal API.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md. The original fork implemented this same login call
twice, once in config_flow.py (via aiohttp) and once in coordinator.py
(via requests), against the same endpoint with the same payload. This
module is now the *only* place either of those makes an HTTP request.

Every method here is a plain blocking call -- callers dispatch to a
worker thread via `hass.async_add_executor_job`, same convention
custom_components/rocky_mountain_power's api.py already uses in this
repo. Sensus's white-label platform is used by 70+ utilities and its
exact JSON shape is confirmed only for the endpoints below (per the HA
community thread that first reverse-engineered this API, and this repo's
own live testing once credentials are available -- see
docs/sensus-analytics-water.md); a different utility's instance could
plausibly differ, hence UnexpectedResponse rather than a bare KeyError
whenever the shape doesn't match what's expected.
"""

from __future__ import annotations

from urllib.parse import urljoin

import requests

from .const import DAILY_WIDGET_PATH, HOURLY_USAGE_PATH_TEMPLATE, LOGIN_PATH, REQUEST_TIMEOUT_SECONDS


class SensusAnalyticsError(Exception):
    """Base error for all Sensus Analytics API failures."""


class CannotConnect(SensusAnalyticsError):
    """Network-level failure talking to the portal."""


class InvalidAuth(SensusAnalyticsError):
    """Login failed -- bad username/password."""


class UnexpectedResponse(SensusAnalyticsError):
    """Portal responded, but not in a shape we understand."""


class SensusAnalyticsClient:
    """Client for one utility's Sensus Analytics instance.

    `login()` is called once per polling cycle by the coordinator (and
    once, standalone, by config_flow.py's credential check) -- matching
    the original fork's behavior of re-authenticating every cycle rather
    than trying to detect and recover from mid-session expiry. Simpler,
    and not something either the original fork or this patch has actually
    needed to handle differently.
    """

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._username = username
        self._password = password
        # Private session: never share cookies across accounts/instances.
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def login(self) -> None:
        """Authenticate, establishing the session cookie subsequent calls need.

        Confirmed (HA community thread that first reverse-engineered this
        API): Sensus's Spring-Security-based login 302-redirects on
        success and does not on failure.
        """
        login_url = urljoin(self._base_url, LOGIN_PATH)
        try:
            response = self._session.post(
                login_url,
                data={"j_username": self._username, "j_password": self._password},
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as err:
            raise CannotConnect(f"Could not reach {login_url}: {err}") from err

        if response.status_code != 302:
            raise InvalidAuth(f"Login rejected (HTTP {response.status_code})")

    def get_daily_data(self, account_number: str, meter_number: str) -> dict:
        """Fetch the daily-usage widget's data for one meter.

        Confirmed response shape:
        `{"widgetList": [{"data": {"devices": [{...the meter's data...}]}}]}`.
        """
        widget_url = urljoin(self._base_url, DAILY_WIDGET_PATH)
        try:
            response = self._session.post(
                widget_url,
                json={"group": "meters", "accountNumber": account_number, "deviceId": meter_number},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as err:
            raise CannotConnect(f"Could not reach {widget_url}: {err}") from err
        except ValueError as err:
            raise UnexpectedResponse(f"Daily widget response was not JSON: {err}") from err

        try:
            return payload["widgetList"][0]["data"]["devices"][0]
        except (KeyError, IndexError, TypeError) as err:
            raise UnexpectedResponse(f"Unexpected daily-widget response shape: {err}") from err

    def get_hourly_data_raw(self, account_number: str, meter_number: str, start_ts_ms: int, end_ts_ms: int) -> dict:
        """Fetch raw hourly usage/rainfall/temperature data for a time window.

        Returns the raw decoded JSON as-is -- extracting the
        units-header-plus-entries shape out of it is
        coordinator.py's job, matching where the original fork already
        did that parsing (and where its existing tests-worth logic
        already lives, kept as-is per the plan).
        """
        usage_url = urljoin(
            self._base_url,
            HOURLY_USAGE_PATH_TEMPLATE.format(account_number=account_number, meter_number=meter_number),
        )
        params = {"start": start_ts_ms, "end": end_ts_ms, "zoom": "day", "page": "null", "weather": "1"}
        try:
            response = self._session.get(usage_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.exceptions.RequestException as err:
            raise CannotConnect(f"Could not reach {usage_url}: {err}") from err

        try:
            return response.json()
        except ValueError as err:
            raise UnexpectedResponse(f"Hourly usage response was not JSON: {err}") from err
