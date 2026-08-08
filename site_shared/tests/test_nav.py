from __future__ import annotations

import pytest

from site_shared.nav import PAGES, render_nav_html


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
