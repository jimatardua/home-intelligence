from __future__ import annotations

from site_shared.theme import (
    DARK,
    LIGHT,
    render_theme_bootstrap_script,
    render_theme_style_block,
    render_theme_watch_script,
)


def test_light_is_the_default_root_block():
    css = render_theme_style_block()

    # The bare :root{...} (no media query, no data-theme attribute) must
    # come first and carry the light palette -- light is the default,
    # dark is the override, matching how the block is structured.
    root_block = css.split("\n")[0]
    assert root_block.startswith(":root{")
    assert f"--bg:{LIGHT.bg}" in root_block
    assert f"--accent:{LIGHT.accent}" in root_block


def test_dark_applies_via_prefers_color_scheme_media_query():
    css = render_theme_style_block()

    assert "@media (prefers-color-scheme: dark)" in css
    media_block = css.split("@media (prefers-color-scheme: dark)")[1]
    assert f"--bg:{DARK.bg}" in media_block


def test_manual_data_theme_overrides_present_for_both_directions():
    css = render_theme_style_block()

    assert ':root[data-theme="dark"]' in css
    assert ':root[data-theme="light"]' in css
    dark_override = css.split(':root[data-theme="dark"]')[1].split(":root[")[0]
    light_override = css.split(':root[data-theme="light"]')[1]
    assert f"--bg:{DARK.bg}" in dark_override
    assert f"--bg:{LIGHT.bg}" in light_override


def test_shared_accent_is_consistent_across_light_and_dark():
    # One brand accent across the whole site, not per-theme competing blues.
    assert LIGHT.accent == DARK.accent == "#4da3ff"


def test_warn_color_has_a_distinct_pair_per_theme():
    # Unlike the accent, warn is read as body text/borders against the
    # background, so it needs real contrast in both directions rather than
    # a single fixed value.
    assert LIGHT.warn != DARK.warn


def test_bootstrap_script_reads_localstorage_before_first_paint():
    script = render_theme_bootstrap_script()

    assert script.startswith("<script>")
    assert script.endswith("</script>")
    assert "localStorage.getItem('theme')" in script
    assert "setAttribute('data-theme'" in script


def test_watch_script_only_redispatches_in_auto_mode():
    script = render_theme_watch_script()

    assert "prefers-color-scheme: dark" in script
    assert "getAttribute('data-theme')" in script
    assert "themechange" in script
