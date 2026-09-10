"""Tests for sensor.py's pure-logic pieces: the tiered-pricing math and
current-hour lookup extracted while porting this fork (see NOTICE.md), and
the unit-conversion mixin carried over unchanged from upstream.

Uses the real `homeassistant` package (installed in this dev environment
specifically to make this possible) rather than the importlib-stub
workaround `test_api.py`/`custom_components/rocky_mountain_power`'s own
tests use for their HA-independent modules -- sensor.py itself imports
real `homeassistant.components.sensor`/`homeassistant.helpers.entity`, so
that workaround doesn't apply here. If `homeassistant` isn't installed,
these tests won't collect at all; `test_api.py` remains runnable without
it.

Lightweight stand-in objects (not a full HA test harness/fixtures) are
used for `coordinator`/`hass`/`config_entry` -- enough attribute surface
for the functions under test, nothing more.
"""

from __future__ import annotations

from datetime import datetime
import zoneinfo

from custom_components.sensus_analytics.sensor import (
    UsageConversionMixin,
    _current_hour_entry,
    _pricing_config,
    _tiered_usage_cost,
)


class _FakeConfigEntry:
    def __init__(self, data: dict):
        self.data = data


class _FakeCoordinator:
    def __init__(self, data: dict, config_entry_data: dict):
        self.data = data
        self.config_entry = _FakeConfigEntry(config_entry_data)


class _FakeHassConfig:
    def __init__(self, time_zone: str):
        self.time_zone = time_zone


class _FakeHass:
    def __init__(self, time_zone: str = "America/Denver"):
        self.config = _FakeHassConfig(time_zone)


class _MixinUnderTest(UsageConversionMixin):
    """Bare object exposing just what the mixin's methods read."""

    def __init__(self, coordinator: _FakeCoordinator):
        self.coordinator = coordinator


# --- _tiered_usage_cost ---------------------------------------------------


def test_tiered_usage_cost_none_usage_returns_zero():
    assert _tiered_usage_cost(None, 0, 0.01, 0, 0, 0) == 0.0


def test_tiered_usage_cost_single_tier_when_tier1_gallons_is_zero():
    # tier1_gallons == 0 means "no limit -- everything at tier 1 price"
    assert _tiered_usage_cost(1000, 0, 0.01, 0, 0, 0) == 1000 * 0.01


def test_tiered_usage_cost_two_tier_under_tier1_limit():
    cost = _tiered_usage_cost(500, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=0, tier2_price=0.02, tier3_price=0)
    assert cost == 500 * 0.01


def test_tiered_usage_cost_two_tier_over_tier1_limit():
    cost = _tiered_usage_cost(1500, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=0, tier2_price=0.02, tier3_price=0)
    assert cost == 1000 * 0.01 + 500 * 0.02


def test_tiered_usage_cost_three_tier_within_tier1():
    cost = _tiered_usage_cost(500, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=1000, tier2_price=0.02, tier3_price=0.03)
    assert cost == 500 * 0.01


def test_tiered_usage_cost_three_tier_within_tier2():
    cost = _tiered_usage_cost(1500, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=1000, tier2_price=0.02, tier3_price=0.03)
    assert cost == 1000 * 0.01 + 500 * 0.02


def test_tiered_usage_cost_three_tier_into_tier3():
    cost = _tiered_usage_cost(2500, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=1000, tier2_price=0.02, tier3_price=0.03)
    assert cost == 1000 * 0.01 + 1000 * 0.02 + 500 * 0.03


def test_tiered_usage_cost_two_tier_config_with_zero_tier3_price_never_reaches_tier3():
    # tier2_gallons > 0 but tier3_price == 0 -- the original fork's (and
    # this fork's) three-way branch treats this as "only 2 tiers actually
    # configured" and returns 0 rather than silently charging $0/gallon
    # for unlimited overage. Documenting this exact (slightly surprising)
    # existing behavior with a test, not silently changing it.
    cost = _tiered_usage_cost(5000, tier1_gallons=1000, tier1_price=0.01, tier2_gallons=1000, tier2_price=0.02, tier3_price=0)
    assert cost == 0.0


# --- _pricing_config -------------------------------------------------------


def test_pricing_config_extracts_all_fields():
    entry = _FakeConfigEntry(
        {
            "tier1_gallons": 1000,
            "tier1_price": 0.01,
            "tier2_gallons": 2000,
            "tier2_price": 0.02,
            "tier3_price": 0.03,
        }
    )
    assert _pricing_config(entry) == (1000, 0.01, 2000, 0.02, 0.03)


def test_pricing_config_defaults_missing_optional_fields_to_zero():
    entry = _FakeConfigEntry({"tier1_price": 0.01})
    assert _pricing_config(entry) == (0, 0.01, 0, 0, 0)


# --- _current_hour_entry ----------------------------------------------------


def test_current_hour_entry_finds_matching_hour():
    hass = _FakeHass()
    tz = zoneinfo.ZoneInfo("America/Denver")
    now_local = datetime.now(tz)
    matching_ts_ms = int(now_local.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
    hourly_data = [
        {"timestamp": matching_ts_ms - 3600_000, "usage": 1},
        {"timestamp": matching_ts_ms, "usage": 42},
    ]

    entry = _current_hour_entry(hass, hourly_data)

    assert entry is not None
    assert entry["usage"] == 42


def test_current_hour_entry_returns_none_when_no_match():
    hass = _FakeHass()
    tz = zoneinfo.ZoneInfo("America/Denver")
    now_local = datetime.now(tz)
    # 12 hours off the current hour can never land on the same hour-of-day,
    # regardless of what time this test happens to run at (unlike a fixed
    # epoch timestamp, which could coincidentally collide).
    non_matching_ts_ms = int((now_local.replace(minute=0, second=0, microsecond=0)).timestamp() * 1000) + 12 * 3600_000
    hourly_data = [{"timestamp": non_matching_ts_ms, "usage": 1}]

    assert _current_hour_entry(hass, hourly_data) is None


def test_current_hour_entry_returns_none_for_empty_list():
    assert _current_hour_entry(_FakeHass(), []) is None


# --- UsageConversionMixin ---------------------------------------------------


def test_convert_usage_none_returns_none():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "GAL"}, {"unit_type": "gal"}))
    assert mixin._convert_usage(None) is None


def test_convert_usage_cf_to_gal():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "CF"}, {"unit_type": "gal"}))
    assert mixin._convert_usage(1) == round(7.48052)


def test_convert_usage_cf_to_ccf():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "CF"}, {"unit_type": "CCF"}))
    assert mixin._convert_usage(250) == 2.5


def test_convert_usage_gal_to_gal_passthrough():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "GAL"}, {"unit_type": "gal"}))
    assert mixin._convert_usage(42) == 42


def test_convert_usage_gal_to_ccf():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "GAL"}, {"unit_type": "CCF"}))
    # 748.052 gallons == 1 CCF
    assert mixin._convert_usage(748.052) == 1.0


def test_convert_usage_unknown_unit_pair_passes_through_unconverted():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "WEIRD"}, {"unit_type": "gal"}))
    assert mixin._convert_usage(5) == 5


def test_convert_usage_non_numeric_returns_none():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "CF"}, {"unit_type": "gal"}))
    assert mixin._convert_usage("not-a-number") is None


def test_get_usage_unit_prefers_configured_unit():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "CF"}, {"unit_type": "gal"}))
    assert mixin._get_usage_unit() == "gal"


def test_get_usage_unit_falls_back_to_api_unit_when_config_unexpected():
    mixin = _MixinUnderTest(_FakeCoordinator({"usageUnit": "CF"}, {"unit_type": "something-else"}))
    assert mixin._get_usage_unit() == "CF"
