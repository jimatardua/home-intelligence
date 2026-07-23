"""Tests for render.py -- manifest.json content and the PWA head tags.

No test file existed yet for render.py; render_manifest_json() is a good
first candidate since it's pure (no ctx, no I/O). render_html() gets one
smoke test for the new PWA meta/link tags -- the rest of render_html's
existing behavior (layout, data binding) has no prior test coverage either
and is out of scope for this change.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from home_dashboard.render import BG_COLOR, DashboardContext, render_data_json, render_html, render_manifest_json

TZ = ZoneInfo("America/Denver")


def _minimal_context() -> DashboardContext:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=TZ)
    return DashboardContext(
        generated_at=now,
        outdoor_temp_f=82.0,
        outdoor_humidity_pct=30.0,
        condition="sunny",
        outdoor_battery_pct=90.0,
        indoor_temp_f=75.0,
        indoor_humidity_pct=40.0,
        hvac_mode="cool",
        hvac_action="idle",
        setpoint_f=76.0,
        setpoint_low_f=None,
        setpoint_high_f=None,
        sunrise=now,
        sunset=now,
        usage_today_ac_kwh=1.0,
        usage_today_ev_kwh=0.0,
    )


def test_manifest_is_valid_json_with_expected_keys():
    manifest = json.loads(render_manifest_json())
    assert manifest["name"] == "Home"
    assert manifest["short_name"] == "Home"
    assert manifest["display"] == "standalone"
    assert manifest["orientation"] == "landscape"
    assert manifest["background_color"] == BG_COLOR
    assert manifest["theme_color"] == BG_COLOR


def test_manifest_colors_match_render_html_shared_constant():
    # Catches a future CSS edit that changes the page's background without
    # updating the constant the manifest also reads from.
    manifest = json.loads(render_manifest_json())
    assert manifest["background_color"] == BG_COLOR
    assert f"--bg:{BG_COLOR}" in render_html(_minimal_context())


def test_manifest_icons_reference_expected_files():
    manifest = json.loads(render_manifest_json())
    icons = {(icon["src"], icon["sizes"]) for icon in manifest["icons"]}
    assert ("apple-touch-icon.png", "180x180") in icons
    assert ("icon-512.png", "512x512") in icons
    for icon in manifest["icons"]:
        assert icon["type"] == "image/png"


def test_manifest_start_url_and_scope_are_relative():
    # Relative, not absolute -- must stay correct regardless of nginx's
    # /dashboard/ mount path, same reasoning as the client's relative
    # fetch('data.json').
    manifest = json.loads(render_manifest_json())
    assert manifest["start_url"] == "."
    assert manifest["scope"] == "."


def test_render_html_includes_pwa_head_tags():
    html = render_html(_minimal_context())
    assert '<link rel="manifest" href="manifest.json">' in html
    assert '<link rel="apple-touch-icon" href="apple-touch-icon.png">' in html
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in html
    assert '<meta name="apple-mobile-web-app-title" content="Home">' in html
    assert f'<meta name="theme-color" content="{BG_COLOR}">' in html


def test_render_html_viewport_has_viewport_fit_cover():
    # Required for env(safe-area-inset-*) to resolve to anything but 0.
    html = render_html(_minimal_context())
    assert "viewport-fit=cover" in html


def _button_up_flag(ctx: DashboardContext) -> bool:
    return json.loads(render_data_json(ctx))["should_button_up_house"]


def test_button_up_house_true_when_ac_off_and_outside_warmer():
    ctx = replace(_minimal_context(), hvac_mode="off", outdoor_temp_f=80.0, indoor_temp_f=75.0)
    assert _button_up_flag(ctx) is True


def test_button_up_house_false_when_ac_running():
    # Same temperatures as above, but the A/C is actually on -- this is the
    # "cool mode with a wide setpoint, waiting to kick in" situation, not
    # the "windows open" situation the flag is meant to catch.
    ctx = replace(_minimal_context(), hvac_mode="cool", outdoor_temp_f=80.0, indoor_temp_f=75.0)
    assert _button_up_flag(ctx) is False


def test_button_up_house_false_when_outside_cooler():
    ctx = replace(_minimal_context(), hvac_mode="off", outdoor_temp_f=70.0, indoor_temp_f=75.0)
    assert _button_up_flag(ctx) is False


def test_button_up_house_false_within_margin():
    # Outside is nominally warmer, but only by less than BUTTON_UP_MARGIN_F --
    # within ordinary sensor noise, shouldn't flip the flag on.
    ctx = replace(_minimal_context(), hvac_mode="off", outdoor_temp_f=75.5, indoor_temp_f=75.0)
    assert _button_up_flag(ctx) is False


def test_button_up_house_false_when_temps_missing():
    ctx = replace(_minimal_context(), hvac_mode="off", outdoor_temp_f=None, indoor_temp_f=75.0)
    assert _button_up_flag(ctx) is False
    ctx = replace(_minimal_context(), hvac_mode="off", outdoor_temp_f=80.0, indoor_temp_f=None)
    assert _button_up_flag(ctx) is False


def test_render_html_indoor_temp_gets_warn_class_toggle_in_script():
    # Smoke test that the client-side wiring (class toggle + fallback
    # message) made it into the rendered page at all.
    html = render_html(_minimal_context())
    assert "should_button_up_house" in html
    assert "button up the house" in html
