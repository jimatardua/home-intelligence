from __future__ import annotations

from control_panel.const import (
    ALEXA_ENTITY,
    DINING_COVERS,
    HVAC_MODES,
    OFFICE_COVERS,
    ROOM_LABELS,
)
from control_panel.render import render_html


def test_render_html_includes_all_hvac_mode_buttons():
    html = render_html()

    for mode in HVAC_MODES:
        assert f'data-mode="{mode}"' in html
    # heat_cool was deliberately dropped -- see const.py's docstring.
    assert 'data-mode="heat_cool"' not in html


def test_render_html_includes_both_room_cards_with_all_three_buttons():
    html = render_html()

    for room in ROOM_LABELS:
        assert f'data-room="{room}" data-position="100"' in html
        assert f'data-room="{room}" data-position="50"' in html
        assert f'data-room="{room}" data-position="0"' in html


def test_render_html_includes_shared_nav_linking_all_four_pages():
    html = render_html()

    assert 'href="/dashboard/"' in html
    assert 'href="/cigars/"' in html
    assert 'href="/energy-report/"' in html
    assert 'href="/control/" class="active"' in html


def test_render_html_includes_swipe_nav_with_no_next_page():
    # Control is the last page in PAGES -- no wraparound.
    html = render_html()

    assert 'prevHref = "/energy-report/"' in html
    assert "nextHref = null" in html


def test_render_html_excludes_theme_toggle():
    html = render_html()

    assert 'id="theme-toggle"' not in html
    assert "data-theme-choice" not in html


def test_render_html_includes_shared_theme_css():
    html = render_html()

    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root[data-theme="dark"]' in html


def test_render_html_fetches_thermostat_and_calls_blinds_api():
    html = render_html()

    assert "/control/api/thermostat" in html
    assert "/control/api/blinds/" in html


def test_render_html_includes_temperature_adjust_buttons():
    html = render_html()

    assert 'id="temp-down"' in html
    assert 'id="temp-up"' in html
    assert 'id="temp-target-value"' in html
    assert "adjustTargetTemp" in html


def test_render_html_updates_temp_and_mode_optimistically_not_via_immediate_refetch():
    # Real bug, confirmed live: the Nest is cloud-synced, so re-fetching
    # immediately after a POST races the cloud round-trip and reads back
    # the *old* value -- it took two presses to register one degree of
    # change. Fix is to update the display from what was just
    # successfully requested, then only re-fetch after a delay.
    html = render_html()

    assert "lastTargetTemp = next" in html
    assert "renderThermoInfo()" in html
    assert "setTimeout(refreshThermostat, REFRESH_AFTER_ACTION_MS)" in html
    # The old bug pattern: refreshThermostat() called with no delay
    # immediately after a POST resolves, inside adjustTargetTemp/the mode
    # button handler specifically (the closing `refreshThermostat();` on
    # its own line, not the setTimeout-wrapped or initial-load calls).
    assert "\n  refreshThermostat();\n" not in html


def test_render_html_never_hardcodes_cover_entity_ids():
    # The page only ever talks to /control/api/blinds/<room> -- entity IDs
    # are resolved server-side (server.py), never sent from the browser.
    html = render_html()

    for entity_id in OFFICE_COVERS + DINING_COVERS:
        assert entity_id not in html


def test_render_html_includes_speaker_card_with_both_buttons():
    html = render_html()

    assert 'data-action="play_relaxing"' in html
    assert 'data-action="stop"' in html
    assert "/control/api/speaker/" in html


def test_render_html_never_hardcodes_the_alexa_entity_id():
    # Same reasoning as the cover entities above -- resolved server-side.
    html = render_html()

    assert ALEXA_ENTITY not in html


def test_render_html_reuses_shared_action_button_wiring_for_speaker_and_blinds():
    # DRY check: the speaker and blind buttons should share one click-wiring
    # helper rather than duplicating the fetch/status-text/pending pattern.
    html = render_html()

    assert "function wireActionButtons(" in html
    assert "wireActionButtons(\n  '.blind-btn'" in html
    assert "wireActionButtons(\n  '.speaker-btn'" in html
