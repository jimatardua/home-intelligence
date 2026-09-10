from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from cigar_dashboard.govee_history import CollectorHealth, DataFreshness, DeviceReading, HistoryPoint
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


# --- Banner: data staleness outranks the collector's self-report ----------


def _freshness(stale=(), all_stale=False, **ages) -> DataFreshness:
    seconds = {"TH01": 30.0, "TH02": 30.0, "TH03": 30.0}
    seconds.update(ages)
    return DataFreshness(
        seconds_since_newest=seconds, stale_device_ids=tuple(stale), all_devices_stale=all_stale
    )


def test_no_banner_when_data_is_flowing_and_collector_is_happy():
    ctx = _minimal_context(data_freshness=_freshness())

    data = json.loads(render_data_json(ctx))
    html = render_html(ctx)

    assert data["banner"]["message"] is None
    assert data["data_freshness"]["is_problem"] is False
    assert 'id="health-banner" style="display:none"' in html


def test_all_devices_stale_banner_names_the_gap_and_contradicts_the_collector():
    # The 2026-09-09 shape exactly: 13 hours of nothing while the collector
    # insisted it was fine. The banner has to say both halves, or a reader
    # checks the collector's "ok" and concludes the dashboard is confused.
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=False, status="ok", seconds_since_last_reading=135.0),
        data_freshness=_freshness(
            stale=("TH01", "TH02", "TH03"), all_stale=True, TH01=13 * 3600.0, TH02=13 * 3600.0, TH03=13 * 3600.0
        ),
    )

    data = json.loads(render_data_json(ctx))
    message = data["banner"]["message"]

    assert "any sensor" in message
    assert "13h 0m" in message
    assert '"ok"' in message  # the claim being contradicted, quoted
    assert data["banner"]["show_fix"] is True
    assert data["data_freshness"]["is_problem"] is True


def test_all_devices_stale_banner_is_visible_on_first_paint_with_the_fix_block():
    ctx = _minimal_context(
        data_freshness=_freshness(stale=("TH01", "TH02", "TH03"), all_stale=True, TH01=3600.0, TH02=3600.0, TH03=3600.0)
    )

    html = render_html(ctx)

    assert 'id="health-banner" style="display:flex"' in html
    assert 'id="health-banner-fix" style="display:block"' in html
    assert RESET_INSTRUCTIONS in html


def test_single_stale_device_names_it_and_hides_the_adapter_reset():
    # One sensor quiet while the others report is a battery/range problem,
    # so the BLE-adapter reset commands are the wrong advice here.
    ctx = _minimal_context(data_freshness=_freshness(stale=("TH02",), TH02=70 * 60.0))

    data = json.loads(render_data_json(ctx))
    html = render_html(ctx)

    assert "Drybox" in data["banner"]["message"]
    assert "1h 10m" in data["banner"]["message"]
    assert data["banner"]["show_fix"] is False
    assert 'id="health-banner-fix" style="display:none"' in html


def test_collector_problem_still_shows_when_data_is_fresh():
    # Fresh data but the collector is retrying -- the old behaviour, still
    # worth surfacing; this check must not have replaced it.
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=True, status="stuck", seconds_since_last_reading=400.0),
        data_freshness=_freshness(),
    )

    data = json.loads(render_data_json(ctx))

    assert "stuck" in data["banner"]["message"]
    assert data["banner"]["show_fix"] is True


def test_stale_data_message_wins_when_both_signals_fire():
    ctx = _minimal_context(
        collector_health=CollectorHealth(is_problem=True, status="stuck", seconds_since_last_reading=400.0),
        data_freshness=_freshness(stale=("TH01", "TH02", "TH03"), all_stale=True, TH01=1800.0, TH02=1800.0, TH03=1800.0),
    )

    message = json.loads(render_data_json(ctx))["banner"]["message"]

    assert "any sensor" in message  # the evidence, not the claim
    assert "appears stuck" not in message


def test_never_seen_device_reads_as_ever_not_as_zero_minutes():
    ctx = _minimal_context(data_freshness=_freshness(stale=("TH03",), TH03=None))

    message = json.loads(render_data_json(ctx))["banner"]["message"]

    assert "in ever" in message  # "No new readings from Desk in ever"
    assert "0m" not in message


def test_page_js_reads_the_prebuilt_banner_rather_than_rebuilding_it():
    # Guards the DRY fix: the message text must exist in one place. If the
    # JS ever goes back to composing its own strings, this fails.
    html = render_html(_minimal_context(data_freshness=_freshness()))

    assert "applyBanner(d.banner)" in html
    assert "automatic retries have failed" not in html.split("<script>")[-1]
