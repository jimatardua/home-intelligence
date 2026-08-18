"""Shared top navigation bar + light/dark/auto toggle for the three
dashboard pages.

Pure string-builder, no I/O. `render_nav_html()` is inlined into each
page's own <body> (its scoped CSS lives in NAV_STYLE, inlined alongside
`theme.render_theme_style_block()` in that page's own <style>) -- same
self-contained-page convention as everything else in this repo.
"""

from __future__ import annotations

from site_shared import theme

# (path, label) -- dict insertion order is the display order.
PAGES: dict[str, tuple[str, str]] = {
    "dashboard": ("/dashboard/", "Home"),
    "cigars": ("/cigars/", "Cigars"),
    "energy-report": ("/energy-report/", "Energy"),
    "control": ("/control/", "Control"),
}

NAV_STYLE = """
.site-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 16px;background:var(--card);border-radius:var(--r,10px);margin-bottom:var(--gap,14px);flex-wrap:wrap}
.site-nav .links{display:flex;gap:4px}
.site-nav a{color:var(--muted);text-decoration:none;font-size:13px;font-weight:600;padding:6px 12px;border-radius:6px}
.site-nav a.active{color:var(--text);background:var(--bg)}
.site-nav a:hover{color:var(--text)}
"""


def _links_html(active_page: str) -> str:
    links = []
    for key, (href, label) in PAGES.items():
        cls = ' class="active"' if key == active_page else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    return "\n    ".join(links)


def _neighbor_hrefs(active_page: str) -> tuple[str | None, str | None]:
    """(prev_href, next_href) in PAGES' fixed display order, or None at
    either end -- not a wraparound carousel; swiping past the last page
    and landing back at the first would surprise more than it'd help."""
    if active_page not in PAGES:
        raise ValueError(f"Unknown active_page: {active_page!r} (expected one of {sorted(PAGES)})")
    keys = list(PAGES)
    i = keys.index(active_page)
    prev_href = PAGES[keys[i - 1]][0] if i > 0 else None
    next_href = PAGES[keys[i + 1]][0] if i < len(keys) - 1 else None
    return prev_href, next_href


# Picked defensively: long enough to not fire on an incidental tap-drag or
# a diagonal scroll, short enough to feel responsive. Like every other
# touch-behavior claim in this project's docs, real-device tuning may
# still be needed -- this is a starting point, not a measured value.
_SWIPE_MIN_PX = 60
_SWIPE_MAX_OFF_AXIS_RATIO = 0.5  # vertical movement must stay under half the horizontal


def render_swipe_nav_script(active_page: str) -> str:
    """A horizontal swipe past a threshold navigates to the next/previous
    page in PAGES' fixed order (Home <-> Cigars <-> Energy) -- a real page
    navigation (full reload), not an animated slide-over: these are
    separate static pages, not a single-page app, same as everywhere else
    in this repo. No-ops at either end rather than wrapping around.

    Also hides the nav's link row entirely on touch-capable devices --
    once swipe works, the links are redundant there, and hiding them
    (rather than reskinning them small, as the kiosk page originally did)
    is what actually makes the three pages' look consistent on an iPad/
    iPhone. Non-touch visitors (e.g. a laptop browser) keep the visible
    links, since swipe isn't available to them as a substitute.
    """
    prev_href, next_href = _neighbor_hrefs(active_page)
    prev_js = f'"{prev_href}"' if prev_href else "null"
    next_js = f'"{next_href}"' if next_href else "null"
    return f"""<script>
(function() {{
  if (('ontouchstart' in window) || navigator.maxTouchPoints > 0) {{
    var siteNav = document.querySelector('.site-nav');
    if (siteNav) {{ siteNav.style.display = 'none'; }}
  }}

  var prevHref = {prev_js};
  var nextHref = {next_js};
  var startX = null, startY = null;

  document.addEventListener('touchstart', function(e) {{
    if (e.touches.length !== 1) {{ startX = null; return; }}
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }}, {{passive: true}});

  document.addEventListener('touchend', function(e) {{
    if (startX === null) return;
    var touch = e.changedTouches[0];
    var dx = touch.clientX - startX;
    var dy = touch.clientY - startY;
    startX = null;
    if (Math.abs(dx) < {_SWIPE_MIN_PX}) return;
    if (Math.abs(dy) > Math.abs(dx) * {_SWIPE_MAX_OFF_AXIS_RATIO}) return;
    if (dx < 0 && nextHref) {{ window.location.href = nextHref; }}
    else if (dx > 0 && prevHref) {{ window.location.href = prevHref; }}
  }}, {{passive: true}});
}})();
</script>"""


def render_nav_html(active_page: str) -> str:
    """Raises ValueError on an unknown `active_page` (mirrors
    home_dashboard/icons.py's ICON_NAMES guard). Renders page links only --
    no theme toggle, on any page: the site always follows
    `prefers-color-scheme` (see theme.py), so there's nothing for a toggle
    to control. Always includes theme.render_theme_watch_script(), since
    every page now needs the "OS scheme changed while open" redraw case it
    covers, not just the pages that used to have a toggle."""
    if active_page not in PAGES:
        raise ValueError(f"Unknown active_page: {active_page!r} (expected one of {sorted(PAGES)})")

    links_html = _links_html(active_page)
    return (
        f'<nav class="site-nav"><div class="links">\n    {links_html}\n  </div></nav>\n'
        f"{theme.render_theme_watch_script()}"
    )
