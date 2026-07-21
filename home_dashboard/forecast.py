"""NWS forecast client -- daily highs/lows and precipitation chance.

Calls NWS's public forecast API (`api.weather.gov`) directly, bypassing Home
Assistant entirely. Modern HA moved forecast data out of the recorder/
state-attributes model into a live `weather.get_forecasts` service call,
which would require a long-lived access token to reach from outside HA --
the same token-vs-manual-step tradeoff already decided against for Matter
commissioning elsewhere in this project. Going straight to NWS's own API
needs no token, no API key, just the same contact-identifier convention
already used for the `pynws` station lookup during NWS setup.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from home_dashboard.weather_icons import icon_category_for_nws_icon_url

CONTACT = "comanche@ardua.com"
USER_AGENT = f"{CONTACT} home-dashboard"
FORECAST_URL = "https://api.weather.gov/gridpoints/SLC/103,174/forecast"
REQUEST_TIMEOUT_SECONDS = 10


class ForecastError(Exception):
    """Raised when the NWS forecast API can't be reached or parsed."""


@dataclass(frozen=True)
class ForecastPeriod:
    """One NWS forecast period (roughly half a day: day or night)."""

    name: str  # e.g. "Today", "Tonight", "Wednesday"
    is_daytime: bool
    temperature_f: int  # that period's high (daytime) or low (nighttime)
    short_forecast: str
    precip_probability_pct: int  # 0 if NWS reports none for this period
    icon_category: str | None  # local icon category, e.g. "partly-cloudy-day" -- see weather_icons.py


def _parse_period(raw: dict) -> ForecastPeriod:
    try:
        precip = raw.get("probabilityOfPrecipitation") or {}
        icon_url = raw.get("icon")
        return ForecastPeriod(
            name=raw["name"],
            is_daytime=raw["isDaytime"],
            temperature_f=int(raw["temperature"]),
            short_forecast=raw["shortForecast"],
            precip_probability_pct=int(precip.get("value") or 0),
            icon_category=icon_category_for_nws_icon_url(icon_url) if icon_url else None,
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ForecastError(f"Unexpected NWS forecast period shape: {raw}") from err


def get_forecast_periods(limit: int = 6) -> list[ForecastPeriod]:
    """Fetch the next `limit` forecast periods (day/night halves) from NWS.

    Raises ForecastError on any network or parsing failure -- callers
    decide whether to fall back to stale/cached data rather than crash the
    whole dashboard generation over a transient NWS outage.
    """
    try:
        response = requests.get(
            FORECAST_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as err:
        raise ForecastError(f"Could not fetch NWS forecast: {err}") from err

    try:
        periods = payload["properties"]["periods"][:limit]
    except (KeyError, TypeError) as err:
        raise ForecastError(f"Unexpected NWS forecast response shape: {payload}") from err

    return [_parse_period(p) for p in periods]
