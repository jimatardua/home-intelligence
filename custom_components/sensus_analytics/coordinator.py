"""DataUpdateCoordinator for the Sensus Analytics integration.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md. All HTTP/auth now goes through api.py's
SensusAnalyticsClient (the original fork owned a `requests.Session`
directly here, duplicating config_flow.py's separate aiohttp-based login
call); the hourly-data JSON-shape parsing below is otherwise unchanged
from the original, since it was already reasonable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CannotConnect, InvalidAuth, SensusAnalyticsClient, UnexpectedResponse
from .const import CONF_ACCOUNT_NUMBER, CONF_METER_NUMBER, DOMAIN, LOGGER, UPDATE_INTERVAL

type SensusAnalyticsConfigEntry = ConfigEntry["SensusAnalyticsCoordinator"]


class SensusAnalyticsCoordinator(DataUpdateCoordinator[dict]):
    """Coordinates polling one meter's daily + hourly Sensus Analytics data."""

    def __init__(self, hass: HomeAssistant, config_entry: SensusAnalyticsConfigEntry, client: SensusAnalyticsClient):
        super().__init__(hass, LOGGER, config_entry=config_entry, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.client = client
        self.account_number = config_entry.data[CONF_ACCOUNT_NUMBER]
        self.meter_number = config_entry.data[CONF_METER_NUMBER]

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(self._fetch_data)
        except InvalidAuth as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except CannotConnect as err:
            raise UpdateFailed(f"Network error: {err}") from err
        except UnexpectedResponse as err:
            raise UpdateFailed(f"Unexpected response from Sensus Analytics: {err}") from err
        return data

    def _fetch_data(self) -> dict:
        """Blocking: log in, fetch daily data, then best-effort hourly data."""
        self.client.login()
        data = self.client.get_daily_data(self.account_number, self.meter_number)

        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        target_date = (datetime.now(local_tz) - timedelta(days=1)).date()
        hourly_data = self._retrieve_hourly_data(target_date)
        if hourly_data:
            data["hourly_usage_data"] = hourly_data
        else:
            LOGGER.warning("Failed to fetch hourly data")

        return data

    def _retrieve_hourly_data(self, target_date) -> list[dict] | None:
        """Best-effort: a failure here shouldn't fail the whole update,
        since daily data (the primary sensors) already succeeded."""
        start_ts, end_ts = self._get_start_end_timestamps(target_date)
        try:
            raw = self.client.get_hourly_data_raw(self.account_number, self.meter_number, start_ts, end_ts)
        except (CannotConnect, UnexpectedResponse) as err:
            LOGGER.error("Hourly data retrieval failed: %s", err)
            return None
        return self._process_hourly_data_response(raw)

    def _get_start_end_timestamps(self, target_date) -> tuple[int, int]:
        """Start/end of `target_date` in local time, as ms timestamps."""
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=local_tz)
        end_dt = datetime.combine(target_date, datetime.max.time(), tzinfo=local_tz)
        return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)

    def _process_hourly_data_response(self, hourly_data: dict) -> list[dict] | None:
        """Unchanged from the original fork -- already reasonable."""
        if not isinstance(hourly_data, dict):
            LOGGER.error("Unexpected response format for hourly data.")
            return None

        if not hourly_data.get("operationSuccess", False):
            LOGGER.error("API returned errors: %s", hourly_data.get("errors", []))
            return None

        usage_list = hourly_data.get("data", {}).get("usage", [])
        if not usage_list or len(usage_list) < 2:
            LOGGER.error("Hourly usage data is missing or incomplete.")
            return None

        # The first element contains units: ["CCF", "INCHES", "FAHRENHEIT", "gal"]
        usage_unit, rain_unit, temp_unit = usage_list[0][:3]

        hourly_entries = []
        for entry in usage_list[1:]:
            timestamp, usage, rain, temp = entry[:4]
            hourly_entries.append(
                {
                    "timestamp": timestamp,
                    "usage": usage,
                    "rain": rain,
                    "temp": temp,
                    "usage_unit": usage_unit,
                    "rain_unit": rain_unit,
                    "temp_unit": temp_unit,
                }
            )
        return hourly_entries
