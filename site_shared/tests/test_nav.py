from __future__ import annotations

import pytest

from site_shared.nav import PAGES, _neighbor_hrefs, render_nav_html, render_swipe_nav_script


def test_render_nav_html_links_all_three_pages():
    html = render_nav_html("cigars")

    for path, label in PAGES.values():
        assert f'href="{path}"' in html
        assert label in html


def test_render_nav_html_highlights_active_page_only():
    html = render_nav_html("cigars")

    assert '<a href="/cigars/" class="active">' in html
    assert '<a href="/dashboard/">' in html
    assert '<a href="/energy-report/">' in html


def test_render_nav_html_raises_on_unknown_page():
    with pytest.raises(ValueError):
        render_nav_html("bogus-page")


def test_render_nav_html_show_toggle_true_includes_toggle_and_script():
    html = render_nav_html("energy-report", show_toggle=True)

    assert 'id="theme-toggle"' in html
    assert "data-theme-choice=\"light\"" in html
    assert "data-theme-choice=\"dark\"" in html
    assert "data-theme-choice=\"auto\"" in html
    assert "themechange" in html
    assert "matchMedia" in html  # composed-in watch script for OS-change-while-auto


def test_render_nav_html_show_toggle_false_omits_toggle_entirely():
    html = render_nav_html("dashboard", show_toggle=False)

    assert "theme-toggle" not in html
    assert "<script>" not in html
    assert "data-theme-choice" not in html


def test_render_nav_html_show_toggle_false_still_links_all_pages():
    html = render_nav_html("dashboard", show_toggle=False)

    for path, label in PAGES.values():
        assert f'href="{path}"' in html
        assert label in html


def test_neighbor_hrefs_first_page_has_no_prev():
    prev_href, next_href = _neighbor_hrefs("dashboard")
    assert prev_href is None
    assert next_href == "/cigars/"


def test_neighbor_hrefs_middle_page_has_both():
    prev_href, next_href = _neighbor_hrefs("cigars")
    assert prev_href == "/dashboard/"
    assert next_href == "/energy-report/"


def test_neighbor_hrefs_last_page_has_no_next():
    prev_href, next_href = _neighbor_hrefs("energy-report")
    assert prev_href == "/cigars/"
    assert next_href is None


def test_neighbor_hrefs_raises_on_unknown_page():
    with pytest.raises(ValueError):
        _neighbor_hrefs("bogus-page")


def test_render_swipe_nav_script_middle_page_has_both_targets():
    html = render_swipe_nav_script("cigars")

    assert 'prevHref = "/dashboard/"' in html
    assert 'nextHref = "/energy-report/"' in html
    assert "touchstart" in html
    assert "touchend" in html


def test_render_swipe_nav_script_first_page_prev_is_null():
    html = render_swipe_nav_script("dashboard")

    assert "prevHref = null" in html
    assert 'nextHref = "/cigars/"' in html


def test_render_swipe_nav_script_last_page_next_is_null():
    html = render_swipe_nav_script("energy-report")

    assert 'prevHref = "/cigars/"' in html
    assert "nextHref = null" in html


def test_render_swipe_nav_script_raises_on_unknown_page():
    with pytest.raises(ValueError):
        render_swipe_nav_script("bogus-page")
