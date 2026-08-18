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


def test_render_nav_html_never_includes_a_toggle():
    # No page has a manual theme override anymore -- the site always
    # follows the OS. Checked across all three pages, not just one.
    for active_page in PAGES:
        html = render_nav_html(active_page)
        assert "theme-toggle" not in html
        assert "data-theme-choice" not in html


def test_render_nav_html_always_includes_the_watch_script():
    # Every page needs the "OS scheme changed while open" redraw case,
    # not just pages that used to have a toggle.
    for active_page in PAGES:
        html = render_nav_html(active_page)
        assert "themechange" in html
        assert "matchMedia" in html


def test_render_nav_html_links_all_pages_for_every_active_page():
    for active_page in PAGES:
        html = render_nav_html(active_page)
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


def test_render_swipe_nav_script_hides_nav_on_touch_devices():
    # Checked across all three pages -- every page gets both the swipe
    # capability and the redundant-nav-hiding it enables, not just one.
    for active_page in PAGES:
        html = render_swipe_nav_script(active_page)
        assert "ontouchstart" in html
        assert "maxTouchPoints" in html
        assert "site-nav" in html
        assert "display = 'none'" in html
