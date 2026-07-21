"""Maps NWS forecast icon URLs to a locally vendored icon category.

NWS's own `/icons` endpoint is marked deprecated, though still functional
with no removal timeline (https://github.com/weather-gov/api/discussions/557).
NWS's own recommended long-term approach is to map their icon condition
codes to custom graphics locally -- this module does exactly that, feeding
home_dashboard.icons's vendored Meteocons set. See docs/home-dashboard.md.

NWS's documented condition-code vocabulary (weather.gov/forecast-icons)
doesn't always match what the live API actually returns: the docs list
"hi_tsra" and "scttsra", but real forecast responses have been observed
using "tsra_hi" and "tsra_sct" instead (modifier and base in the opposite
order). Rather than maintain an exact-match list that silently falls back
to a generic default whenever NWS's real ordering differs from the docs
(exactly what happened during development -- every thunderstorm period
came out as plain "cloudy"), each condition segment is classified by
substring, and the most severe classification wins when a period packs
multiple segments together.
"""

from __future__ import annotations

from urllib.parse import urlparse

from home_dashboard.icons import ICON_NAMES

DEFAULT_ICON_CATEGORY = "cloudy"

# Most attention-grabbing first: when an NWS icon URL packs multiple
# condition segments into one period (e.g. "bkn/tsra_hi,40" -- cloudy early
# in the period, thunderstorms later), the more severe one wins.
_CATEGORY_SEVERITY = [
    "thunderstorms",
    "sleet",
    "snow",
    "rain",
    "drizzle",
    "wind",
    "smoke",
    "fog",
    "cloudy",
    "partly-cloudy",
    "clear",
]

_CATEGORIES_WITH_DAY_NIGHT = {"clear", "partly-cloudy", "thunderstorms"}

assert DEFAULT_ICON_CATEGORY in ICON_NAMES
assert set(_CATEGORY_SEVERITY) - _CATEGORIES_WITH_DAY_NIGHT | _CATEGORIES_WITH_DAY_NIGHT == set(_CATEGORY_SEVERITY)


def _classify_code(code: str) -> str:
    """Classifies a single NWS condition code (no day/night suffix) by substring.

    Order matters -- more specific/severe substrings are checked first so a
    compound code (e.g. "wind_bkn", "tsra_sct") doesn't get caught by a
    later, more generic check for one of its component parts.
    """
    if code in ("tor", "fc"):
        return "thunderstorms"
    if "hur_warn" in code or "hur_watch" in code:
        return "wind"
    if "ts_warn" in code or "ts_watch" in code or "ts_nowarn" in code:
        return "thunderstorms"
    if "tsra" in code:
        return "thunderstorms"
    if "blizzard" in code:
        return "snow"
    if "fzra" in code or "raip" in code or "snip" in code or "ra_sn" in code:
        return "sleet"
    if code == "ip":
        return "sleet"
    if "minus_ra" in code:
        return "drizzle"
    if "shwrs" in code or "shra" in code:
        return "rain"
    if code == "ra":
        return "rain"
    if "sn" in code:
        return "snow"
    if "wind" in code:
        return "wind"
    if "fu" in code:
        return "smoke"
    if "du" in code or "hz" in code or "fg" in code:
        return "fog"
    if "hot" in code or "cold" in code:
        return "clear"
    if "ovc" in code or "bkn" in code:
        return "cloudy"
    if "sct" in code or "few" in code:
        return "partly-cloudy"
    if "skc" in code:
        return "clear"
    return DEFAULT_ICON_CATEGORY


def icon_category_for_nws_icon_url(url: str) -> str:
    """Derives a local icon category (e.g. "clear-day") from an NWS icon URL.

    NWS packs the URL path as `.../icons/{land|marine}/{day|night}/{code}[,pct][/{code}[,pct]]`
    -- a second condition segment represents a within-period transition (an
    early condition giving way to a later one); the more severe of the two
    wins. Everything after the "day"/"night" marker is treated as a
    condition code, regardless of how many fixed segments precede it --
    classifying a stray non-condition segment (e.g. "icons") would otherwise
    contribute a spurious DEFAULT_ICON_CATEGORY into the severity ranking,
    which can beat a real but lower-severity category like "clear".

    Falls back to DEFAULT_ICON_CATEGORY for anything unrecognized: an
    approximate icon is harmless in a way a fabricated sensor reading would
    not be, and NWS's condition vocabulary isn't a fixed, versioned contract.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    try:
        marker = next(i for i, p in enumerate(parts) if p in ("day", "night"))
    except StopIteration:
        return DEFAULT_ICON_CATEGORY
    is_daytime = parts[marker] == "day"

    codes = [p.split(",", 1)[0] for p in parts[marker + 1 :]]
    if not codes:
        return DEFAULT_ICON_CATEGORY

    categories = [_classify_code(code) for code in codes]
    best = min(categories, key=_CATEGORY_SEVERITY.index)

    if best in _CATEGORIES_WITH_DAY_NIGHT:
        return f"{best}-{'day' if is_daytime else 'night'}"
    return best
