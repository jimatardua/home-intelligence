"""Tests for weather_icons.py -- NWS icon URL to local icon category mapping."""

from __future__ import annotations

from home_dashboard.icons import ICON_NAMES
from home_dashboard.weather_icons import DEFAULT_ICON_CATEGORY, icon_category_for_nws_icon_url


def _url(path: str) -> str:
    return f"https://api.weather.gov/icons/{path}?size=medium"


def test_leading_icons_path_segment_does_not_pollute_the_severity_ranking():
    # Regression: the real NWS URL is "https://api.weather.gov/icons/land/day/skc"
    # -- the "icons" path segment sits before "land", not after "day"/"night".
    # A version of this mapping that classified every non-day/night segment
    # (including "icons" itself) fell back to DEFAULT_ICON_CATEGORY
    # ("cloudy") for it, and "cloudy" outranked the real "clear"/
    # "partly-cloudy" classification in the severity ranking -- so every
    # clear or partly-cloudy forecast period silently came out as "cloudy".
    assert icon_category_for_nws_icon_url("https://api.weather.gov/icons/land/day/skc?size=medium") == "clear-day"
    assert (
        icon_category_for_nws_icon_url("https://api.weather.gov/icons/land/day/few?size=medium")
        == "partly-cloudy-day"
    )


def test_simple_day_clear():
    assert icon_category_for_nws_icon_url(_url("land/day/skc")) == "clear-day"


def test_simple_night_clear():
    assert icon_category_for_nws_icon_url(_url("land/night/skc")) == "clear-night"


def test_few_and_sct_both_map_to_partly_cloudy():
    assert icon_category_for_nws_icon_url(_url("land/day/few")) == "partly-cloudy-day"
    assert icon_category_for_nws_icon_url(_url("land/night/sct")) == "partly-cloudy-night"


def test_bkn_and_ovc_map_to_cloudy_with_no_day_night_variant():
    assert icon_category_for_nws_icon_url(_url("land/day/bkn")) == "cloudy"
    assert icon_category_for_nws_icon_url(_url("land/night/ovc")) == "cloudy"


def test_rain_has_no_night_variant():
    assert icon_category_for_nws_icon_url(_url("land/day/ra")) == "rain"
    assert icon_category_for_nws_icon_url(_url("land/night/shra")) == "rain"


def test_thunderstorms_has_day_and_night_variants():
    assert icon_category_for_nws_icon_url(_url("land/day/tsra")) == "thunderstorms-day"
    assert icon_category_for_nws_icon_url(_url("land/night/tsra")) == "thunderstorms-night"


def test_wintry_mix_codes_map_to_sleet():
    for code in ("ra_sn", "raip", "fzra", "ra_fzra", "fzra_sn", "ip", "snip"):
        assert icon_category_for_nws_icon_url(_url(f"land/day/{code}")) == "sleet"


def test_light_rain_maps_to_drizzle():
    assert icon_category_for_nws_icon_url(_url("land/day/minus_ra")) == "drizzle"


def test_snow_and_blizzard_map_to_snow():
    assert icon_category_for_nws_icon_url(_url("land/day/sn")) == "snow"
    assert icon_category_for_nws_icon_url(_url("land/night/blizzard")) == "snow"


def test_smoke_vs_dust_and_haze():
    assert icon_category_for_nws_icon_url(_url("land/day/fu")) == "smoke"
    assert icon_category_for_nws_icon_url(_url("land/day/du")) == "fog"
    assert icon_category_for_nws_icon_url(_url("land/day/hz")) == "fog"
    assert icon_category_for_nws_icon_url(_url("land/day/fg")) == "fog"


def test_wind_combo_codes_map_to_wind():
    assert icon_category_for_nws_icon_url(_url("land/day/wind_skc")) == "wind"
    assert icon_category_for_nws_icon_url(_url("land/night/wind_bkn")) == "wind"


def test_two_segment_transition_prefers_more_severe_condition():
    # A real observed shape: cloudy early in the period, thunderstorms later.
    assert icon_category_for_nws_icon_url(_url("land/day/bkn/tsra_hi,40")) == "thunderstorms-day"


def test_two_segment_transition_order_does_not_matter():
    assert icon_category_for_nws_icon_url(_url("land/night/tsra_hi,40/bkn")) == "thunderstorms-night"


def test_real_observed_modifier_orderings_not_in_the_official_docs():
    # NWS's docs (weather.gov/forecast-icons) list "hi_tsra" and "scttsra",
    # but real forecast responses captured live used "tsra_hi" and
    # "tsra_sct" instead -- modifier and base swapped. A previous, stricter
    # exact-match version of this mapping missed these and silently fell
    # back to "cloudy" for every thunderstorm period.
    assert icon_category_for_nws_icon_url(_url("land/night/tsra_sct,50")) == "thunderstorms-night"
    assert icon_category_for_nws_icon_url(_url("land/day/bkn/tsra_sct,60")) == "thunderstorms-day"


def test_unrecognized_code_falls_back_to_default_not_a_crash():
    assert icon_category_for_nws_icon_url(_url("land/day/some_new_code_nws_added")) == DEFAULT_ICON_CATEGORY


def test_no_condition_segments_falls_back_to_default():
    assert icon_category_for_nws_icon_url(_url("land/day")) == DEFAULT_ICON_CATEGORY


def test_every_severity_category_is_a_known_icon_name_or_has_day_night_variants():
    from home_dashboard.weather_icons import _CATEGORIES_WITH_DAY_NIGHT, _CATEGORY_SEVERITY

    for category in _CATEGORY_SEVERITY:
        if category in _CATEGORIES_WITH_DAY_NIGHT:
            assert f"{category}-day" in ICON_NAMES
            assert f"{category}-night" in ICON_NAMES
        else:
            assert category in ICON_NAMES
