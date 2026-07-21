"""Loads locally vendored weather icons (Meteocons, flat style, MIT license).

Icons are vendored as static SVG <symbol> fragments under icons/ rather than
hotlinked from NWS or a CDN, matching the rest of this package's "the page
must be self-contained" stance (the same reasoning behind embedding the
NoSleep video fallback directly rather than loading it from elsewhere).
Source: https://meteocons.com (basmilius/meteocons on GitHub), MIT licensed.
See docs/home-dashboard.md for how this was chosen over NWS's own
(deprecated) icon server and over hand-drawn icons.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ICON_NAMES = frozenset(
    {
        "clear-day",
        "clear-night",
        "partly-cloudy-day",
        "partly-cloudy-night",
        "cloudy",
        "rain",
        "drizzle",
        "sleet",
        "snow",
        "thunderstorms-day",
        "thunderstorms-night",
        "fog",
        "smoke",
        "wind",
        # Not NWS forecast conditions -- used directly by the Sun card,
        # not via weather_icons.py's condition-code mapping. Two changes
        # from the original Meteocons artwork: the horizon line's stroke
        # color (#202939 -> this page's --muted gray #8b93a7, since the
        # original was nearly invisible against the dashboard's near-black
        # background), and the sun's "peeking over the horizon" crop is
        # baked directly into the path/circle geometry rather than done via
        # a <mask>/<clipPath> -- the original mask-based crop silently
        # failed to apply when instantiated via <use> from within this
        # sprite (confirmed via a side-by-side render; other vendored icons
        # that use an internal mask happen to look correct anyway only
        # because an opaque shape drawn on top, e.g. a cloud, coincidentally
        # covers the same overflow). The three rays that would cross the
        # horizon are simply omitted rather than clipped.
        "sunrise",
        "sunset",
    }
)

_ICONS_DIR = Path(__file__).parent / "icons"


@lru_cache(maxsize=None)
def load_icon_svg(name: str) -> str:
    """Returns the vendored `<symbol>` markup for a known icon category."""
    if name not in ICON_NAMES:
        raise ValueError(f"Unknown icon category: {name!r}")
    return (_ICONS_DIR / f"{name}.svg").read_text()


def load_icon_sprite() -> str:
    """Returns all icons concatenated into one hidden SVG sprite.

    Embedded once in the page shell (render_html) since it never changes
    across a session; the forecast strip then references icons by id via
    `<use href="#icon-NAME">`, keeping the 60-second data.json refresh down
    to a plain category string instead of repeating SVG markup.
    """
    symbols = "\n".join(load_icon_svg(name) for name in sorted(ICON_NAMES))
    return f'<svg style="display:none" aria-hidden="true">\n{symbols}</svg>'
