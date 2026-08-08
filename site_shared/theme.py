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
    """Light default + dark override via `prefers-color-scheme` + a manual
    `data-theme` override for the light/dark/auto toggle (nav.py) -- no
    `data-theme` attribute set at all means "auto", i.e. just follow the OS.
    Callers embed this directly inside their own `<style>...</style>` tags
    (it's the `:root{...}` rules only, not a full stylesheet)."""
    return (
        f":root{{{_vars(LIGHT)}}}\n"
        f"@media (prefers-color-scheme: dark){{:root{{{_vars(DARK)}}}}}\n"
        f':root[data-theme="dark"]{{{_vars(DARK)}}}\n'
        f':root[data-theme="light"]{{{_vars(LIGHT)}}}'
    )


def render_theme_bootstrap_script() -> str:
    """Tiny, synchronous <script> -- reads localStorage and sets
    `data-theme` on <html> BEFORE first paint. Must be inlined early in
    <head>, not at the end of <body> like every other script block in
    these pages, or the page flashes its default theme before the saved
    override applies (FOUC). Included on every page, even the kiosk (which
    has no toggle UI of its own to ever write this key) -- localStorage is
    shared across all three pages on this origin, so a choice made on
    /cigars/ or /energy-report/ in the same browser should still be
    honored consistently if that browser ever loads /dashboard/ too."""
    return (
        "<script>"
        "(function(){"
        "try{"
        "var t=localStorage.getItem('theme');"
        "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);"
        "}catch(e){}"
        "})();"
        "</script>"
    )


def render_theme_watch_script() -> str:
    """Redispatches a `themechange` DOM event whenever the OS scheme
    changes while the page is open AND no manual override is active
    (i.e. currently in `auto` mode) -- needed for pages that stay open
    indefinitely, the kiosk in particular (iOS's system dark mode can
    auto-switch on a schedule while the display never reloads), so chart
    colors that can't be pure CSS (inline SVG stroke attributes, Chart.js
    canvas fills) still follow. `nav.py`'s toggle script covers the
    click-driven case and calls this separately rather than duplicating
    the same `matchMedia` listener."""
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
