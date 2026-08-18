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
}

NAV_STYLE = """
.site-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 16px;background:var(--card);border-radius:var(--r,10px);margin-bottom:var(--gap,14px);flex-wrap:wrap}
.site-nav .links{display:flex;gap:4px}
.site-nav a{color:var(--muted);text-decoration:none;font-size:13px;font-weight:600;padding:6px 12px;border-radius:6px}
.site-nav a.active{color:var(--text);background:var(--bg)}
.site-nav a:hover{color:var(--text)}
.theme-toggle{display:flex;gap:2px;background:var(--bg);border-radius:6px;padding:2px}
.theme-toggle button{border:none;background:none;color:var(--muted);font-size:12px;font-weight:600;padding:5px 10px;border-radius:5px;cursor:pointer}
.theme-toggle button.active{background:var(--card);color:var(--text)}
"""


def _links_html(active_page: str) -> str:
    links = []
    for key, (href, label) in PAGES.items():
        cls = ' class="active"' if key == active_page else ""
        links.append(f'<a href="{href}"{cls}>{label}</a>')
    return "\n    ".join(links)


_TOGGLE_HTML = """<div class="theme-toggle" id="theme-toggle">
    <button data-theme-choice="light">Light</button>
    <button data-theme-choice="dark">Dark</button>
    <button data-theme-choice="auto" class="active">Auto</button>
  </div>"""

# Click-handling + initial button-state only -- the "OS scheme changed while
# in auto mode" case is handled by theme.render_theme_watch_script()
# (composed in below), not duplicated here.
_TOGGLE_SCRIPT = """<script>
(function(){
  var root = document.documentElement;
  var buttons = document.querySelectorAll('#theme-toggle button');

  function currentChoice() {
    var saved = null;
    try { saved = localStorage.getItem('theme'); } catch (e) {}
    return (saved === 'light' || saved === 'dark') ? saved : 'auto';
  }

  function applyChoice(choice) {
    if (choice === 'auto') {
      root.removeAttribute('data-theme');
      try { localStorage.removeItem('theme'); } catch (e) {}
    } else {
      root.setAttribute('data-theme', choice);
      try { localStorage.setItem('theme', choice); } catch (e) {}
    }
    buttons.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-theme-choice') === choice);
    });
    document.dispatchEvent(new CustomEvent('themechange'));
  }

  buttons.forEach(function(b) {
    b.addEventListener('click', function() { applyChoice(b.getAttribute('data-theme-choice')); });
  });

  applyChoice(currentChoice());
})();
</script>"""


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
    """
    prev_href, next_href = _neighbor_hrefs(active_page)
    prev_js = f'"{prev_href}"' if prev_href else "null"
    next_js = f'"{next_href}"' if next_href else "null"
    return f"""<script>
(function() {{
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


def render_nav_html(active_page: str, *, show_toggle: bool = True) -> str:
    """Raises ValueError on an unknown `active_page` (mirrors
    home_dashboard/icons.py's ICON_NAMES guard). When `show_toggle` is
    False (the kiosk-safe variant, home_dashboard), renders page links
    only -- no tap target, no toggle script, no room needed in that page's
    hand-tuned vh/vw layout budget."""
    if active_page not in PAGES:
        raise ValueError(f"Unknown active_page: {active_page!r} (expected one of {sorted(PAGES)})")

    links_html = _links_html(active_page)

    if not show_toggle:
        return f'<nav class="site-nav"><div class="links">\n    {links_html}\n  </div></nav>'

    return (
        f'<nav class="site-nav"><div class="links">\n    {links_html}\n  </div>\n'
        f"  {_TOGGLE_HTML}</nav>\n"
        f"{_TOGGLE_SCRIPT}\n"
        f"{theme.render_theme_watch_script()}"
    )
