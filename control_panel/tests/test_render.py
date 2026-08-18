from __future__ import annotations

from control_panel.const import HVAC_MODES, OFFICE_COVERS, DINING_COVERS, ROOM_LABELS
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


def test_render_html_never_hardcodes_cover_entity_ids():
    # The page only ever talks to /control/api/blinds/<room> -- entity IDs
    # are resolved server-side (server.py), never sent from the browser.
    html = render_html()

    for entity_id in OFFICE_COVERS + DINING_COVERS:
        assert entity_id not in html
