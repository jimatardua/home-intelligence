"""Shared light/dark/auto theme tokens for the three dashboard pages.

Pure string-builder module, no I/O -- same shape as
home_dashboard/icons.py's load_icon_sprite(). Each page's own render.py
inlines this CSS/script directly into its own <style>/<head>, matching the
"every page is self-contained, no external CSS/JS files" convention already
used everywhere in this repo -- there's no shared static asset serving, no
new nginx location, nothing to deploy beyond this Python source.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    bg: str
    card: str
    text: str
    muted: str
    accent: str
    warn: str


# Dark palette reuses home_dashboard/cigar_dashboard's already-tuned values
# unchanged. Light palette is a fresh design -- energy_report's old light
# palette was a loose reference, but its accent (#2563eb) is reconciled to
# the shared #4da3ff here, since 2 of the 3 pages already used that blue --
# one brand accent across all three pages, not three competing blues.
# `warn` gets a real light/dark pair (unlike per-series identity colors,
# which stay fixed across themes) since it's read as body text/borders,
# not a fixed data-series color.
LIGHT = ThemePalette(bg="#f0f2f5", card="#ffffff", text="#212529", muted="#6c757d", accent="#4da3ff", warn="#dc2626")
DARK = ThemePalette(bg="#0b0e14", card="#161b26", text="#f2f4f8", muted="#8b93a7", accent="#4da3ff", warn="#ef4444")


def _vars(p: ThemePalette) -> str:
    return f"--bg:{p.bg};--card:{p.card};--text:{p.text};--muted:{p.muted};--accent:{p.accent};--warn:{p.warn}"


def render_theme_style_block() -> str:
    """Light default + dark override via `prefers-color-scheme`, plus a
    manual `[data-theme]` override rule kept for completeness even though
    nothing currently sets that attribute (no toggle exists -- the site
    always follows the OS). No `data-theme` attribute set at all means
    "auto". Callers embed this directly inside their own
    `<style>...</style>` tags (it's the `:root{...}` rules only, not a
    full stylesheet)."""
    return (
        f":root{{{_vars(LIGHT)}}}\n"
        f"@media (prefers-color-scheme: dark){{:root{{{_vars(DARK)}}}}}\n"
        f':root[data-theme="dark"]{{{_vars(DARK)}}}\n'
        f':root[data-theme="light"]{{{_vars(LIGHT)}}}'
    )


def render_theme_bootstrap_script() -> str:
    """Tiny, synchronous <script>, inlined early in <head> on every page.

    There's no toggle anywhere anymore (the site always follows
    `prefers-color-scheme`), so nothing ever writes `localStorage['theme']`
    again -- but this actively clears any leftover value from before that
    change, rather than silently leaving it there. Without this, anyone
    who'd previously clicked "Dark"/"Light" would stay stuck in that
    manual override forever, with no UI left to undo it."""
    return "<script>try{localStorage.removeItem('theme');}catch(e){}</script>"


def render_theme_watch_script() -> str:
    """Redispatches a `themechange` DOM event whenever the OS scheme
    changes while the page is open (every page is always in `auto` mode
    now -- no manual override exists) -- needed for pages that stay open
    indefinitely, the kiosk in particular (iOS's system dark mode can
    auto-switch on a schedule while the display never reloads), so chart
    colors that can't be pure CSS (inline SVG stroke attributes, Chart.js
    canvas fills) still follow. Called unconditionally from
    `nav.render_nav_html()` on every page."""
    return (
        "<script>"
        "if(window.matchMedia){"
        "window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',function(){"
        "if(!document.documentElement.getAttribute('data-theme'))"
        "document.dispatchEvent(new CustomEvent('themechange'));"
        "});"
        "}"
        "</script>"
    )
