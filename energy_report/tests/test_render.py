"""Tests for render.py's chart-series wiring.

Minimal coverage of the new south-side/carport temperature series added
alongside the existing north-side one -- see test_generate_report.py's
module docstring for why this is scoped narrowly rather than backfilling
full coverage of the pre-existing chart code.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from energy_report.render import DailyBreakdown, ReportContext, _chart_series, render_report


def _day(d: date, avg_outdoor_temp_f=None, avg_carport_temp_f=None) -> DailyBreakdown:
    return DailyBreakdown(
        d=d,
        ac_kwh=1.0,
        ev_kwh=0.0,
        other_kwh=2.0,
        onpeak_kwh=1.0,
        offpeak_kwh=2.0,
        hours_present=24,
        hours_expected=24,
        avg_outdoor_temp_f=avg_outdoor_temp_f,
        avg_carport_temp_f=avg_carport_temp_f,
    )


def test_chart_series_includes_south_temperature_alongside_north():
    daily = [
        _day(date(2026, 7, 20), avg_outdoor_temp_f=91.234, avg_carport_temp_f=80.456),
    ]
    series = _chart_series(daily)
    assert series["temp_f"] == [91.2]
    assert series["temp_f_south"] == [80.5]


def test_chart_series_south_temperature_gap_day_is_none_not_zero():
    daily = [
        _day(date(2026, 7, 20), avg_outdoor_temp_f=91.0, avg_carport_temp_f=None),
    ]
    series = _chart_series(daily)
    assert series["temp_f"] == [91.0]
    assert series["temp_f_south"] == [None]


def _minimal_ctx(**overrides) -> ReportContext:
    defaults = dict(
        generated_at=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
        data_as_of=datetime(2026, 8, 8, 11, 0, tzinfo=timezone.utc),
        day_count=5,
        date_range_start=date(2026, 8, 1),
        date_range_end=date(2026, 8, 5),
        hour_coverage_pct=95.0,
        seasons_observed=frozenset({"summer"}),
        maturity_tier="early",
        observed_schedule1_cost=100.0,
        observed_tou_cost=95.0,
        summer_monthly_projection=None,
        summer_annual_projection=None,
        winter_available=False,
        sensitivity_rows=[],
        daily_breakdown=[],
        tariff_effective_date=date(2026, 1, 1),
    )
    defaults.update(overrides)
    return ReportContext(**defaults)


def test_render_report_includes_shared_nav_linking_all_three_pages():
    html = render_report(_minimal_ctx())

    assert 'href="/dashboard/"' in html
    assert 'href="/cigars/"' in html
    assert 'href="/energy-report/" class="active"' in html


def test_render_report_includes_theme_toggle():
    html = render_report(_minimal_ctx())

    assert 'id="theme-toggle"' in html
    assert 'data-theme-choice="auto"' in html


def test_render_report_includes_shared_theme_css():
    html = render_report(_minimal_ctx())

    assert "@media (prefers-color-scheme: dark)" in html
    assert ':root[data-theme="dark"]' in html


def test_render_report_has_no_pwa_manifest_or_touch_icon_links():
    # energy_report explicitly should not become independently installable
    # -- only home_dashboard gets a manifest link.
    html = render_report(_minimal_ctx())

    assert 'rel="manifest"' not in html
    assert 'rel="apple-touch-icon"' not in html


def test_render_report_chart_instances_are_named_for_theme_redraw():
    html = render_report(_minimal_ctx())

    assert "const disaggChart = new Chart(" in html
    assert "const peakChart = new Chart(" in html
    assert "const tempChart = new Chart(" in html
    assert "document.addEventListener('themechange', applyChartTheme)" in html
