from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from cigar_dashboard.govee_history import CollectorHealth, DeviceReading, HistoryPoint
from cigar_dashboard.render import (
    DEVICE_COLORS,
    RESET_INSTRUCTIONS,
    DashboardContext,
    render_data_json,
    render_html,
)

LOCAL_TZ = timezone(timedelta(hours=-6))


def _minimal_context(**overrides) -> DashboardContext:
    defaults = dict(
        generated_at=datetime(2026, 8, 7, 12, 0, tzinfo=LOCAL_TZ),
        readings={
            "TH01": DeviceReading(label="Wineador", temp_f=68.5, humidity_pct=65.2, battery_pct=92),
            "TH02": DeviceReading(label="Drybox", temp_f=70.1, humidity_pct=45.0, battery_pct=88),
            "TH03": DeviceReading(label="Desk", temp_f=74.3, humidity_pct=38.0, battery_pct=95),
        },
        humidity_history={},
        temp_history={},
    )
    defaults.update(overrides)
    return DashboardContext(**defaults)


def test_data_json_includes_all_three_devices_with_correct_values():
    ctx = _minimal_context()

    data = json.loads(render_data_json(ctx))

    assert data["devices"]["TH01"]["label"] == "Wineador"
    assert data["devices"]["TH01"]["humidity_pct"] == 65.2
    assert data["devices"]["TH01"]["temp_f"] == 68.5
    assert data["devices"]["TH01"]["battery_pct"] == 92
    assert data["devices"]["TH02"]["label"] == "Drybox"
    assert data["devices"]["TH03"]["label"] == "Desk"


def test_data_json_carries_a_stable_color_per_device():
    ctx = _minimal_context()

    data = json.loads(render_data_json(ctx))

    for device_id, color in DEVICE_COLORS.items():
        assert data["devices"][device_id]["color"] == color


def test_data_json_missing_device_reading_is_none_not_fabricated():
    ctx = _minimal_context(
        readings={
            "TH01": DeviceReading(label="Wineador", temp_f=None, humidity_pct=None, battery_pct=None),
            "TH02": DeviceReading(label="Drybox", temp_f=70.1, humidity_pct=45.0, battery_pct=88),
            "TH03": DeviceReading(label="Desk", temp_f=74.3, humidity_pct=38.0, battery_pct=95),
        }
    )

    data = json.loads(render_data_json(ctx))

    assert data["devices"]["TH01"]["temp_f"] is None
    assert data["devices"]["TH01"]["humidity_pct"] is None


def test_data_json_history_shape():
    ctx = _minimal_context(
        humidity_history={
            "TH01": [
                HistoryPoint(at_local=datetime(2026, 8, 1, 0, 0, tzinfo=LOCAL_TZ), value=64.0),
                HistoryPoint(at_local=datetime(2026, 8, 7, 0, 0, tzinfo=LOCAL_TZ), value=65.2),
            ]
        }
    )

    data = json.loads(render_data_json(ctx))

    assert data["humidity_history"]["TH01"] == [
        {"t": "2026-08-01T00:00:00-06:00", "v": 64.0},
        {"t": "2026-08-07T00:00:00-06:00", "v": 65.2},
    ]


def test_render_html_shows_missing_reading_as_dashes():
    ctx = _minimal_context(
        readings={
            "TH01": DeviceReading(label="Wineador", temp_f=None, humidity_pct=None, battery_pct=None),
            "TH02": DeviceReading(label="Drybox", temp_f=70.1, humidity_pct=45.0, battery_pct=88),
            "TH03": DeviceReading(label="Desk", temp_f=74.3, humidity_pct=38.0, battery_pct=95),
        }
    )

    html = render_html(ctx)

    assert 'id="humidity-TH01">--<' in html
    assert 'id="temp-TH01">--<' in html


def test_render_html_includes_device_labels_and_current_values():
    ctx = _minimal_context()

    html = render_html(ctx)

    assert "Wineador" in html
    assert "Drybox" in html
    assert "Desk" in html
    assert 'id="humidity-TH01">65%<' in html
    # 68.5 -- Python's `:.0f` uses round-half-to-even, so this is 68, not 69.
    assert 'id="temp-TH01">68°F<' in html


def test_render_html_is_valid_json_embedded_snapshot():
    ctx = _minimal_context()

    html = render_html(ctx)

    # The initial data snapshot must be embedded as real, parseable JSON
    # (first paint before the client-side fetch completes) -- not just
    # present as text. Anchored on the call site specifically (`applyData({`
    # immediately followed by a JSON object), not the `function applyData(d)`
    # definition earlier in the same script, which also matches a naive
    # "applyData(" search.
    marker = "applyData({"
    start = html.index(marker) + len("applyData(")
    end = html.index(");\n", start)
    embedded = html[start:end]
    parsed = json.loads(embedded)
    assert parsed["devices"]["TH01"]["label"] == "Wineador"


def test_data_json_includes_collector_health():
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=True, status="stuck", seconds_since_last_reading=612.0)
    )

    data = json.loads(render_data_json(ctx))

    assert data["collector_health"] == {
        "is_problem": True,
        "status": "stuck",
        "seconds_since_last_reading": 612.0,
    }


def test_render_html_hides_health_banner_when_ok():
    ctx = _minimal_context(collector_health=CollectorHealth(is_problem=False, status="ok", seconds_since_last_reading=4.0))

    html = render_html(ctx)

    assert 'id="health-banner" style="display:none"' in html


def test_render_html_shows_health_banner_when_stuck():
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=True, status="stuck", seconds_since_last_reading=612.0)
    )

    html = render_html(ctx)

    assert 'id="health-banner" style="display:flex"' in html
    assert "automatic retries have failed" in html


def test_render_html_shows_health_banner_when_stale_with_duration():
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=True, status="stale", seconds_since_last_reading=245.0)
    )

    html = render_html(ctx)

    assert 'id="health-banner" style="display:flex"' in html
    assert "245s" in html
    assert "retrying automatically" in html


def test_render_html_shows_health_banner_when_status_unknown():
    ctx = _minimal_context(collector_health=CollectorHealth(is_problem=True, status=None, seconds_since_last_reading=None))

    html = render_html(ctx)

    assert 'id="health-banner" style="display:flex"' in html
    assert "unknown" in html.lower()


def test_render_html_always_includes_the_manual_reset_commands():
    # Even when hidden by CSS, the fix instructions must be present in the
    # markup so the client-side JS can reveal them without a second fetch --
    # and so the exact commands are directly copy-pasteable from the page
    # the moment someone sees the banner, no doc-digging required.
    ctx = _minimal_context()

    html = render_html(ctx)

    assert RESET_INSTRUCTIONS in html
    assert "hciconfig hci0 down" in html
    assert "systemctl restart govee-collector" in html


def test_render_html_includes_shared_nav_linking_all_three_pages():
    ctx = _minimal_context()

    html = render_html(ctx)

    assert 'href="/dashboard/"' in html
    assert 'href="/cigars/" class="active"' in html
    assert 'href="/energy-report/"' in html


def test_render_html_includes_swipe_nav_to_both_neighbors():
    ctx = _minimal_context()

    html = render_html(ctx)

    assert 'prevHref = "/dashboard/"' in html
    assert 'nextHref = "/energy-report/"' in html


def test_render_html_excludes_theme_toggle():
    # No manual override anywhere -- the site always follows the OS.
    ctx = _minimal_context()

    html = render_html(ctx)

    assert 'id="theme-toggle"' not in html
    assert "data-theme-choice" not in html


def test_render_html_includes_shared_theme_css():
    ctx = _minimal_context()

    html = render_html(ctx)

    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root[data-theme="dark"]' in html


def test_render_html_has_no_pwa_manifest_or_touch_icon_links():
    # Explicitly should not become independently installable -- only
    # home_dashboard gets a manifest link.
    ctx = _minimal_context()

    html = render_html(ctx)

    assert 'rel="manifest"' not in html
    assert 'rel="apple-touch-icon"' not in html


def test_render_html_redraws_charts_on_themechange_from_cached_data():
    ctx = _minimal_context()

    html = render_html(ctx)

    assert "document.addEventListener('themechange'" in html
    assert "let lastData = null;" in html
