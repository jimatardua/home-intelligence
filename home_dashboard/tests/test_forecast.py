"""Tests for forecast.py -- NWS forecast API client."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from home_dashboard.forecast import ForecastError, get_forecast_periods

# A trimmed real response shape, captured live against api.weather.gov
# during development -- matches the exact fields _parse_period() reads.
_SAMPLE_RESPONSE = {
    "properties": {
        "periods": [
            {
                "name": "Today",
                "isDaytime": True,
                "temperature": 98,
                "shortForecast": "Partly Sunny then Chance Showers And Thunderstorms",
                "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 40},
            },
            {
                "name": "Tonight",
                "isDaytime": False,
                "temperature": 70,
                "shortForecast": "Chance Showers And Thunderstorms",
                "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 51},
            },
        ]
    }
}


def _mock_response(json_body: dict, status_code: int = 200) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    return resp


def test_get_forecast_periods_parses_real_shape():
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(_SAMPLE_RESPONSE)):
        periods = get_forecast_periods()

    assert len(periods) == 2
    assert periods[0].name == "Today"
    assert periods[0].is_daytime is True
    assert periods[0].temperature_f == 98
    assert periods[0].precip_probability_pct == 40
    assert periods[1].name == "Tonight"
    assert periods[1].is_daytime is False


def test_icon_url_extracted_when_present():
    body = {
        "properties": {
            "periods": [
                {
                    "name": "Today",
                    "isDaytime": True,
                    "temperature": 98,
                    "shortForecast": "Sunny",
                    "icon": "https://api.weather.gov/icons/land/day/skc?size=medium",
                }
            ]
        }
    }
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(body)):
        [period] = get_forecast_periods()
    assert period.icon_url == "https://api.weather.gov/icons/land/day/skc?size=medium"


def test_missing_icon_field_becomes_none_not_a_crash():
    body = {
        "properties": {
            "periods": [
                {"name": "Today", "isDaytime": True, "temperature": 98, "shortForecast": "Sunny"}
            ]
        }
    }
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(body)):
        [period] = get_forecast_periods()
    assert period.icon_url is None


def test_get_forecast_periods_respects_limit():
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(_SAMPLE_RESPONSE)):
        periods = get_forecast_periods(limit=1)
    assert len(periods) == 1


def test_missing_precip_field_becomes_zero_not_a_crash():
    body = {
        "properties": {
            "periods": [
                {"name": "Today", "isDaytime": True, "temperature": 80, "shortForecast": "Clear"}
            ]
        }
    }
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(body)):
        [period] = get_forecast_periods()
    assert period.precip_probability_pct == 0


def test_network_failure_raises_forecast_error():
    with patch("home_dashboard.forecast.requests.get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(ForecastError):
            get_forecast_periods()


def test_http_error_status_raises_forecast_error():
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response({}, status_code=503)):
        with pytest.raises(ForecastError):
            get_forecast_periods()


def test_malformed_response_shape_raises_forecast_error():
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response({"unexpected": "shape"})):
        with pytest.raises(ForecastError):
            get_forecast_periods()


def test_malformed_period_shape_raises_forecast_error():
    body = {"properties": {"periods": [{"name": "Today"}]}}  # missing required fields
    with patch("home_dashboard.forecast.requests.get", return_value=_mock_response(body)):
        with pytest.raises(ForecastError):
            get_forecast_periods()
