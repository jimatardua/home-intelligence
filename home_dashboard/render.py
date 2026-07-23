"""Renders the home dashboard -- a Carrot Weather replacement for the iPad.

Two outputs, both written by `generate_dashboard.py`:
- `index.html`: the page shell, embedding an initial data snapshot so the
  first paint isn't blank before the first live fetch completes.
- `data.json`: the same data, refetched by the page's own client-side JS
  every 60 seconds and applied in place -- no full-page reload, unlike the
  TOU report's `<meta http-equiv="refresh">` pattern, which would cause a
  jarring flash on an always-on glanceable display.

The current-time display ticks every second via a separate client-side
`setInterval` using the browser's own clock -- no server round-trip needed
for that at all.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
import json

from home_dashboard.icons import load_icon_sprite

# Shared with both the CSS (:root custom properties) and manifest.json's
# background_color/theme_color, so the two can't silently drift apart.
BG_COLOR = "#0b0e14"
CARD_COLOR = "#161b26"
TEXT_COLOR = "#f2f4f8"
MUTED_COLOR = "#8b93a7"
ACCENT_COLOR = "#4da3ff"
WARN_COLOR = "#ef4444"

# "Free cooling" (A/C off, windows open) turns into free heating once it's
# warmer outside than in -- this margin keeps the button-up-the-house
# warning from flickering on/off from ordinary sensor noise right at the
# crossover point, since the two readings come from different sensors.
BUTTON_UP_MARGIN_F = 1.0

# PWA home-screen icons (180x180 apple-touch-icon, 512x512 for manifest.json)
# -- a sun glyph matching the vendored "clear-day" Meteocons icon's amber
# tone, drawn via Pillow (a one-off dev-machine script, not a runtime
# dependency -- see docs/home-dashboard.md). Stored as base64 here and
# decoded to real files by generate_dashboard.py rather than referenced as
# data: URIs directly, since Mobile Safari has a long-standing quirk where
# apple-touch-icon doesn't reliably honor data: URIs.
_APPLE_TOUCH_ICON_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAYAAAA9zQYyAAAFdklEQVR4nO3cS27iQBSFYUCZRepJZX+9tuwvNYnErKW0rFZaQMD4Ua97zv8tILHLPzcVAz4eBvD66+2r9zFgv/Pnx/HQWZcDIGAP5w6BN/uFROzt3Cjuqr+EiNE67io/mJDRK+xT6R9IzOjZSrFXCCFjhGldZEITM0ZpaNergpAx2rTePKGJGbXsaWtT0MSM2rY2tjpoYkYrW1pbFTQxo7W1zS0OmpjRy5r2FgVNzOhtaYNPgyZmjGJJi8Xf+gZ6mg2a6YzRPGvyYdDEjFHNtcmWA1LuBs10xugeNfojaGJGFPdaZcsBKVdBM50RzW2zTGhIeel9AKry+/2lTb//ND8WJ/8nNNsNRHXZLlsOSCFo6AXNdgPRfTfMhIYUgoYUgoaUE/tnqJhaZkJDCkFDCkFDCkFDCkFDCkFDCkFDCkFDyknpw/PAKWrMRF1/jSM6Rnrr+95C85WmemucAn5d7BR9akSeJqPJN2sZcW3DBD03LSIu/GiyyMAIE/SEqOvIM9FG23aECnpC1GVloZhDBj0h6jKyWMxhg54Q9T5ZMObQQU+IepssGnP4oCdEvU4Wjlki6AlRL5PFYw73TmGUC7bm3m2r48qDrE1tUkH3eHu8xhsPpY83m8QsGXSLzyO0fPes1PFnk8/BSAb9fQFbTrraSpxLDv7BI+ugSxrp8wx7Q8wVXugjIeggId9SjvLgftvOLeYIx9cLQQeOJcpxtsSWQyQQtiD/MKEFYlY4/lIIWiiGLHIee9gHrRZBFjuftayDVr34WfS8lrANWv2iZ/Hze8Q2aGiyDNplemWT87QO2u0iZ7PztQra7eI6nrdV0NBnE7TTlHI+f5ug4cEiaJfp9IzDOlgEDR/yQTtMpTWy+HrIBw0vBA0p0kGr/3ndKguvi3TQ8EPQkELQkELQkCIbtPI/PiVk0fWRDRqeXqJNAx6ogjmaf3dgO4zYckAKQUMKQUMKQUNKk38KuTOBVrjLAalhxJYDUmSDjjZZWkui6yMbNDwRNKQQNKQQNKRIB636j89eSXhdpIOGH4KGFPmglf+8bpHE10M+aHixCFp9Ki2VDNbBImj4sAnaYTrNcTl/m6DhwSpolynlfN5WQbtdXMfztQva6SInk/M8uAcNXbZBq0+vJH5+j9gGrXzRk+h5LWEdtOLFT2Lns5Z90EoRJJHz2IOgRWKIfvylHF9/vX0V+2kiIj3dnpCvMaEDRxLlOFuSDnrPpB09ltGPrxfZLcdlzHsv/khbkBIh5/cX2ReEZND3AiwVQi+lAswFX+gjkgt6LroaUdRWMrpc6YU+EqmgW8S85nduVeNYc4e16UEm6JEu2JrIWx5bHmiNapEI2uFClZLF1yr8bTv1C1RamlmTke7mWAZNzNsk4ajDBk3M+yTRqEMGTcxlJMGowwVNzGUlsahDBU3MdSShqE8KC8/djHprGy3qUEHfW3hirre2Edc47BsrUT4x9mi6jXzsOfAHmMJN6KgLHXFtU8A1Dhs06koBY54QNKQQNKQQNKQQNKQQNKQQNKQQNKQQNKQQNKSczp8fx94HAZQwtcyEhhSChhSChl7Q7KMR3XfDTGhIIWhoBs22A1Fdtnt1Dzrq17Hg7XwRNFsOSLkKmm0HorltlgkNKT+CZkojinut3p3QRI3RPWqULQekPAyaKY1RzbU5O6GJGqN51iRbDkh5GjRTGqNY0uKiCU3U6G1pg4u3HESNXta0t2oPTdRobW1zq/8pJGq0sqW1TXc5iBq1bW1s8207okYte9oq8pAZvhiAEkoMySJvrDCtMUpDxR8DxrRGz2FY/K1vpjV6tlL1QY1Ma7Qees2ePErc3s6NnnLb5VG6xO3h3OFRzUM8G5rANZwHeNb4X/G8IqGzLGJrAAAAAElFTkSuQmCC"
)

_APP_ICON_512_PNG_BASE64 = (
    "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"
)


def apple_touch_icon_png_bytes() -> bytes:
    return base64.b64decode(_APPLE_TOUCH_ICON_PNG_BASE64)


def app_icon_512_png_bytes() -> bytes:
    return base64.b64decode(_APP_ICON_512_PNG_BASE64)


# A minimal (1.7KB) silent, black, 2x2px, 2-second H.264 video, base64-encoded
# -- the classic NoSleep.js-style keep-awake trick for iOS versions older
# than the Wake Lock API (iPadOS < 16.4). Generated once via:
#   ffmpeg -f lavfi -i color=c=black:s=2x2:r=1:d=2 -c:v libx264 -pix_fmt yuv420p nosleep.mp4
_NOSLEEP_VIDEO_BASE64 = (
    "AAAAJGZ0eXBpc29tAAACAGlzb21pc282aXNvMmF2YzFtcDQxAAAC7m1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAAA+gAAAAAAAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAHxdHJhawAAAFx0a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAACAAAAAgAAAAABjW1kaWEAAAAgbWRoZAAAAAAAAAAAAAAAAAAAQAAAAAAAVcQAAAAAAC1oZGxyAAAAAAAAAAB2aWRlAAAAAAAAAAAAAAAAVmlkZW9IYW5kbGVyAAAAAThtaW5mAAAAFHZtaGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAD4c3RibAAAAKxzdHNkAAAAAAAAAAEAAACcYXZjMQAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAACAAIASAAAAEgAAAAAAAAAARVMYXZjNjIuMTEuMTAwIGxpYngyNjQAAAAAAAAAAAAAABj//wAAADZhdmNDAWQACv/hABlnZAAKrNlfiIjARAAAAwAEAAADAAg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAQc3R0cwAAAAAAAAAAAAAAEHN0c2MAAAAAAAAAAAAAABRzdHN6AAAAAAAAAAAAAAAAAAAAEHN0Y28AAAAAAAAAAAAAAChtdmV4AAAAIHRyZXgAAAAAAAAAAQAAAAEAAAAAAAAAAAAAAAAAAABhdWR0YQAAAFltZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAACxpbHN0AAAAJKl0b28AAAAcZGF0YQAAAAEAAAAATGF2ZjYyLjMuMTAwAAAAeG1vb2YAAAAQbWZoZAAAAAAAAAABAAAAYHRyYWYAAAAkdGZoZAAAADkAAAABAAAAAAAAAxIAAEAAAAACxQEBAAAAAAAUdGZkdAEAAAAAAAAAAAAAAAAAACB0cnVuAAACBQAAAAIAAACAAgAAAAAAAsUAAAAMAAAC2W1kYXQAAAKtBgX//6ncRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY1IHIzMjIyIGIzNTYwNWEgLSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDI1IC0gaHR0cDovL3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9uczogY2FiYWM9MSByZWY9MyBkZWJsb2NrPTE6MDowIGFuYWx5c2U9MHgzOjB4MTEzIG1lPWhleCBzdWJtZT03IHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4ZWRfcmVmPTEgbWVfcmFuZ2U9MTYgY2hyb21hX21lPTEgdHJlbGxpcz0xIDh4OGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MSBzY2VuZWN1dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTQwIHJjPWNyZiBtYnRyZWU9MSBjcmY9MjMuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBtYXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAABBliIQAFv/+99M/zLLsmiWBAAAACEGaIWxBX/7wAAAAQ21mcmEAAAArdGZyYQEAAAAAAAABAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAMSAQEBAAAAEG1mcm8AAAAAAAAAQw=="
)


@dataclass(frozen=True)
class ForecastPeriodView:
    name: str
    is_daytime: bool
    temperature_f: int
    short_forecast: str
    precip_probability_pct: int
    icon_category: str | None = None  # e.g. "partly-cloudy-day" -- see weather_icons.py


@dataclass(frozen=True)
class TempHistoryPoint:
    at_local: datetime
    temp_f: float


@dataclass(frozen=True)
class DashboardContext:
    generated_at: datetime

    outdoor_temp_f: float | None
    outdoor_humidity_pct: float | None
    condition: str | None  # prettified NWS condition, e.g. "Partly Cloudy"
    outdoor_battery_pct: float | None  # Eve Weather's own battery level

    indoor_temp_f: float | None
    indoor_humidity_pct: float | None
    hvac_mode: str | None  # "cool" | "heat" | "heat_cool" | "off" | None
    hvac_action: str | None  # "cooling" | "heating" | "idle" | "off" | None
    setpoint_f: float | None  # single-setpoint modes (cool/heat)
    setpoint_low_f: float | None  # heat_cool mode
    setpoint_high_f: float | None  # heat_cool mode

    sunrise: datetime
    sunset: datetime

    usage_today_ac_kwh: float
    usage_today_ev_kwh: float

    forecast_periods: list[ForecastPeriodView] = field(default_factory=list)
    outdoor_temp_history: list[TempHistoryPoint] = field(default_factory=list)


# HA's fixed weather-condition enum (homeassistant.components.weather.const)
# -- several are single compound words with no separator (e.g.
# "partlycloudy"), so a generic replace/title() transform can't prettify
# these correctly; an explicit mapping is the only correct approach.
_CONDITION_LABELS = {
    "clear-night": "Clear",
    "cloudy": "Cloudy",
    "exceptional": "Exceptional",
    "fog": "Foggy",
    "hail": "Hail",
    "lightning": "Lightning",
    "lightning-rainy": "Thunderstorms",
    "partlycloudy": "Partly Cloudy",
    "pouring": "Pouring Rain",
    "rainy": "Rainy",
    "snowy": "Snowy",
    "snowy-rainy": "Snow and Rain",
    "sunny": "Sunny",
    "windy": "Windy",
    "windy-variant": "Windy",
}


def _prettify_condition(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _CONDITION_LABELS.get(raw, raw.replace("-", " ").title())


def _fmt_temp(v: float | None) -> str:
    return f"{v:.0f}°" if v is not None else "--"


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p")


def _thermostat_label(ctx: DashboardContext) -> str:
    if ctx.hvac_mode in (None, "off"):
        return "Off"
    if ctx.setpoint_low_f is not None and ctx.setpoint_high_f is not None:
        return f"{ctx.setpoint_low_f:.0f}°-{ctx.setpoint_high_f:.0f}°"
    if ctx.setpoint_f is not None:
        return f"{ctx.setpoint_f:.0f}°"
    return "--"


def _should_button_up_house(ctx: DashboardContext) -> bool:
    """True when the A/C is off and it's warmer outside than in.

    The household's routine: turn the A/C off and open windows overnight
    for free cooling, then close back up once outside catches up to (and
    passes) the indoor temperature -- otherwise open windows start passively
    heating the house instead. Gated on hvac_mode == "off" specifically
    (not just hvac_action == "idle", which would also be true mid-cycle in
    "cool" mode waiting for its setpoint -- a different, intentional
    situation, not this one). Fails closed (False) on any missing reading,
    matching this project's gap-aware convention elsewhere: no alert is
    better than a false one built on absent data.
    """
    if ctx.hvac_mode != "off":
        return False
    if ctx.outdoor_temp_f is None or ctx.indoor_temp_f is None:
        return False
    return ctx.outdoor_temp_f > ctx.indoor_temp_f + BUTTON_UP_MARGIN_F


def _data_dict(ctx: DashboardContext) -> dict:
    return {
        "generated_at": ctx.generated_at.isoformat(),
        "outdoor_temp_f": ctx.outdoor_temp_f,
        "outdoor_humidity_pct": ctx.outdoor_humidity_pct,
        "condition": _prettify_condition(ctx.condition),
        "outdoor_battery_pct": ctx.outdoor_battery_pct,
        "indoor_temp_f": ctx.indoor_temp_f,
        "indoor_humidity_pct": ctx.indoor_humidity_pct,
        "hvac_mode": ctx.hvac_mode,
        "hvac_action": ctx.hvac_action,
        "thermostat_label": _thermostat_label(ctx),
        "should_button_up_house": _should_button_up_house(ctx),
        "sunrise": _fmt_time(ctx.sunrise),
        "sunset": _fmt_time(ctx.sunset),
        "usage_today_ac_kwh": ctx.usage_today_ac_kwh,
        "usage_today_ev_kwh": ctx.usage_today_ev_kwh,
        "forecast": [
            {
                "name": p.name,
                "is_daytime": p.is_daytime,
                "temperature_f": p.temperature_f,
                "short_forecast": p.short_forecast,
                "precip_probability_pct": p.precip_probability_pct,
                "icon_category": p.icon_category,
            }
            for p in ctx.forecast_periods
        ],
        "outdoor_temp_history": [
            {"t": p.at_local.isoformat(), "v": p.temp_f} for p in ctx.outdoor_temp_history
        ],
    }


def render_data_json(ctx: DashboardContext) -> str:
    return json.dumps(_data_dict(ctx))


def render_manifest_json() -> str:
    """Web app manifest for "Add to Home Screen" installs.

    No live data involved -- generated fresh on every cron run anyway (like
    index.html/data.json) so it shares BG_COLOR with the CSS rather than
    duplicating the hex value. Relative start_url/scope (".") so it's
    correct regardless of nginx's /dashboard/ mount path, matching the
    existing relative fetch('data.json') convention.

    "orientation": "landscape" matches how the target iPad is physically
    mounted, but note iOS Safari has never actually honored this field for
    standalone web apps (that's a Chrome/Android behavior) -- included
    because it's spec-correct and free, not because it does anything on
    the real device.
    """
    return json.dumps(
        {
            "name": "Home",
            "short_name": "Home",
            "start_url": ".",
            "scope": ".",
            "display": "standalone",
            "orientation": "landscape",
            "background_color": BG_COLOR,
            "theme_color": BG_COLOR,
            "icons": [
                {"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        }
    )


def render_html(ctx: DashboardContext) -> str:
    initial_data = json.dumps(_data_dict(ctx))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>Home</title>
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Home">
<meta name="theme-color" content="{BG_COLOR}">
<style>
:root{{--bg:{BG_COLOR};--card:{CARD_COLOR};--text:{TEXT_COLOR};--muted:{MUTED_COLOR};--accent:{ACCENT_COLOR};--r:16px;--gap:16px}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%;overflow:hidden}}
/* env(safe-area-inset-*) needs viewport-fit=cover above to be non-zero at
   all -- real and correct, but a no-op on the target iPad Air 2 itself
   (physical home button, no notch/rounded corners); kept for correctness
   on any other device this might run on. */
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;padding:max(4vh,env(safe-area-inset-top)) max(2vw,env(safe-area-inset-right)) max(2vh,env(safe-area-inset-bottom)) max(2vw,env(safe-area-inset-left));gap:var(--gap)}}
.hero{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--gap)}}
.outdoor{{text-align:center}}
.outdoor .temp{{font-size:min(10vw,90px);font-weight:800;line-height:1}}
.outdoor .condition{{font-size:min(3vw,22px);color:var(--muted)}}
.battery-corner{{position:fixed;bottom:max(1vh,env(safe-area-inset-bottom));right:max(1vw,env(safe-area-inset-right));font-size:min(1.8vw,13px);color:var(--muted)}}
.hero-stats{{display:flex;gap:6vw}}
.hero-stats .stat{{text-align:center}}
.hero-stats .stat-value{{font-size:min(5.6vw,48px);font-weight:800;line-height:1}}
.hero-stats .stat-label{{font-size:min(2vw,16px);color:var(--muted);margin-top:2px}}
.clock-block{{text-align:right}}
.clock{{font-size:min(5.6vw,48px);font-weight:800;line-height:1;letter-spacing:-1px}}
.date{{font-size:min(2vw,16px);color:var(--muted);margin-top:2px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--gap)}}
.card{{background:var(--card);border-radius:var(--r);padding:3vh 2vw}}
.card .label{{font-size:min(2vw,13px);color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}}
.card .value{{font-size:min(5vw,40px);font-weight:700}}
.card .value.warn{{color:{WARN_COLOR}}}
.card .sub{{font-size:min(2.2vw,15px);color:var(--muted);margin-top:6px}}
.card .sub.warn{{color:{WARN_COLOR};font-weight:600}}
.sun-row{{display:flex;justify-content:space-around;align-items:center}}
.sun-item{{display:flex;flex-direction:column;align-items:center;gap:4px}}
.sun-item svg.icon{{width:min(11vw,64px);height:min(11vw,64px)}}
.sun-item .sun-time{{font-size:min(2.4vw,17px);font-weight:700}}
.sparkline-card{{background:var(--card);border-radius:var(--r);padding:1.5vh 2vw}}
.sparkline-card .label{{font-size:min(2vw,13px);color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px}}
.sparkline-card svg{{width:100%;height:11vh;display:block}}
.forecast{{background:var(--card);border-radius:var(--r);padding:2vh 2vw;display:flex;justify-content:space-between;gap:8px}}
.period{{flex:1;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:2px}}
.period .name{{font-size:min(2.2vw,15px);color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.period svg.icon{{width:min(8vw,48px);height:min(8vw,48px)}}
.period .temp{{font-size:min(4vw,32px);font-weight:700}}
.period .cond{{font-size:min(2vw,13px);color:var(--muted)}}
.period .rain{{font-size:min(2vw,13px);color:var(--accent);font-weight:600}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}.forecast{{flex-wrap:wrap}}}}
</style>
</head>
<body>

{load_icon_sprite()}

<div class="hero">
  <div class="hero-stats">
    <div class="stat">
      <div class="stat-value" id="rain-chance">--</div>
      <div class="stat-label">Chance of rain</div>
    </div>
    <div class="stat">
      <div class="stat-value" id="humidity">--</div>
      <div class="stat-label">Humidity</div>
    </div>
  </div>
  <div class="outdoor">
    <div class="temp" id="outdoor-temp">--</div>
    <div class="condition" id="outdoor-condition"></div>
  </div>
  <div class="clock-block">
    <div class="clock" id="clock">--:--</div>
    <div class="date" id="date"></div>
  </div>
</div>

<div class="cards">
  <div class="card">
    <div class="label">Indoor</div>
    <div class="value" id="indoor-temp">--</div>
    <div class="sub" id="thermostat-sub"></div>
  </div>
  <div class="card">
    <div class="sun-row">
      <div class="sun-item">
        <svg class="icon"><use href="#icon-sunrise"></use></svg>
        <div class="sun-time" id="sunrise-time">--</div>
      </div>
      <div class="sun-item">
        <svg class="icon"><use href="#icon-sunset"></use></svg>
        <div class="sun-time" id="sunset-time">--</div>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="label">A/C + EV Today (est.)</div>
    <div class="value" id="usage-value">--</div>
    <div class="sub">Estimate of these two loads only, not total house usage</div>
  </div>
</div>

<div class="sparkline-card">
  <div class="label" id="sparkline-label">Outdoor temp -- last 12h</div>
  <svg id="sparkline-svg" viewBox="0 0 600 100" preserveAspectRatio="none"></svg>
</div>

<div class="forecast" id="forecast"></div>

<div class="battery-corner" id="battery"></div>

<!-- Silent, looping, muted 2x2px black video -- a pre-Wake-Lock-API trick
     (the same one NoSleep.js uses) for browsers too old for
     navigator.wakeLock (iPadOS < 16.4). Embedded as a data URI rather than
     a separate asset file so the page stays self-contained. -->
<video id="nosleep-video" muted loop playsinline webkit-playsinline style="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0.01;pointer-events:none">
  <source src="data:video/mp4;base64,{_NOSLEEP_VIDEO_BASE64}" type="video/mp4">
</video>

<script>
const REFRESH_MS = 60000;

function drawSparkline(history) {{
  const svg = document.getElementById('sparkline-svg');
  const label = document.getElementById('sparkline-label');
  if (!history || history.length < 2) {{
    svg.innerHTML = '';
    label.textContent = 'Outdoor temp -- last 12h (not enough data yet)';
    return;
  }}
  const width = 600, height = 100;
  const padLeft = 34, padRight = 6, padTop = 10, padBottom = 18;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const times = history.map(p => new Date(p.t).getTime());
  const temps = history.map(p => p.v);
  const minT = Math.min(...times), maxT = Math.max(...times);
  const minV = Math.min(...temps), maxV = Math.max(...temps);
  const spanT = (maxT - minT) || 1;
  const spanV = (maxV - minV) || 1;
  const xFor = t => padLeft + plotW * ((t - minT) / spanT);
  const yFor = v => padTop + plotH - plotH * ((v - minV) / spanV);
  const timeFmt = t => new Date(t).toLocaleTimeString([], {{hour: 'numeric', minute: '2-digit'}});

  const points = history
    .map(p => xFor(new Date(p.t).getTime()).toFixed(1) + ',' + yFor(p.v).toFixed(1))
    .join(' ');

  let svgHtml = `<polyline points="${{points}}" fill="none" stroke="#4da3ff" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>`;

  // y-axis: a gridline + label at the min and max temperature.
  [minV, maxV].forEach(v => {{
    const y = yFor(v).toFixed(1);
    svgHtml += `<line x1="${{padLeft}}" y1="${{y}}" x2="${{width - padRight}}" y2="${{y}}" stroke="#2a2f3a" stroke-width="1"/>`;
    svgHtml += `<text x="${{padLeft - 6}}" y="${{y}}" text-anchor="end" dominant-baseline="middle" font-size="11" fill="#8b93a7">${{Math.round(v)}}°</text>`;
  }});

  // x-axis: a time label at the start, middle, and end of the window.
  [
    [minT, 'start'],
    [(minT + maxT) / 2, 'middle'],
    [maxT, 'end'],
  ].forEach(([t, anchor]) => {{
    const x = xFor(t).toFixed(1);
    svgHtml += `<text x="${{x}}" y="${{height - 4}}" text-anchor="${{anchor}}" font-size="11" fill="#8b93a7">${{timeFmt(t)}}</text>`;
  }});

  svg.innerHTML = svgHtml;
  label.textContent = 'Outdoor temp -- last 12h';
}}

function applyData(d) {{
  document.getElementById('outdoor-temp').textContent = d.outdoor_temp_f != null ? Math.round(d.outdoor_temp_f) + '°' : '--';
  document.getElementById('outdoor-condition').textContent = d.condition || '';
  document.getElementById('battery').textContent = d.outdoor_battery_pct != null ? '🔋 ' + Math.round(d.outdoor_battery_pct) + '%' : '';

  const currentPeriod = d.forecast && d.forecast[0];
  document.getElementById('rain-chance').textContent = currentPeriod ? currentPeriod.precip_probability_pct + '%' : '--';
  document.getElementById('humidity').textContent = d.outdoor_humidity_pct != null ? Math.round(d.outdoor_humidity_pct) + '%' : '--';

  const indoorTempEl = document.getElementById('indoor-temp');
  indoorTempEl.textContent = d.indoor_temp_f != null ? Math.round(d.indoor_temp_f) + '°' : '--';
  indoorTempEl.classList.toggle('warn', !!d.should_button_up_house);

  const hvac = d.hvac_action && d.hvac_action !== 'off' ? d.hvac_action : (d.hvac_mode || 'off');
  const thermostatSubEl = document.getElementById('thermostat-sub');
  thermostatSubEl.classList.toggle('warn', !!d.should_button_up_house);
  thermostatSubEl.textContent = d.should_button_up_house
    ? 'Outside is warmer -- button up the house'
    : 'Set to ' + d.thermostat_label + ' (' + hvac + ')';

  document.getElementById('sunrise-time').textContent = d.sunrise;
  document.getElementById('sunset-time').textContent = d.sunset;

  const usageTotal = (d.usage_today_ac_kwh || 0) + (d.usage_today_ev_kwh || 0);
  document.getElementById('usage-value').textContent = usageTotal.toFixed(1) + ' kWh';

  const forecastEl = document.getElementById('forecast');
  forecastEl.innerHTML = '';
  (d.forecast || []).forEach(p => {{
    const div = document.createElement('div');
    div.className = 'period';
    const rainHtml = p.precip_probability_pct > 0 ? `<div class="rain">${{p.precip_probability_pct}}% rain</div>` : '';
    const iconHtml = p.icon_category ? `<svg class="icon"><use href="#icon-${{p.icon_category}}"></use></svg>` : '';
    div.innerHTML = `<div class="name">${{p.name}}</div>${{iconHtml}}<div class="temp">${{p.temperature_f}}°</div><div class="cond">${{p.short_forecast}}</div>${{rainHtml}}`;
    forecastEl.appendChild(div);
  }});

  drawSparkline(d.outdoor_temp_history);
}}

applyData({initial_data});

async function refreshData() {{
  try {{
    const res = await fetch('data.json', {{cache: 'no-store'}});
    applyData(await res.json());
  }} catch (err) {{
    // Transient fetch failure -- keep showing the last-known-good data
    // rather than blanking the display.
  }}
}}
setInterval(refreshData, REFRESH_MS);

function tick() {{
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString([], {{hour: 'numeric', minute: '2-digit'}});
  document.getElementById('date').textContent = now.toLocaleDateString([], {{weekday: 'long', month: 'long', day: 'numeric'}});
}}
tick();
setInterval(tick, 1000);

// Keep the display awake -- this is meant to run as an always-on glanceable
// screen. Safari/iPadOS 16.4+ supports the Wake Lock API; re-request it on
// visibilitychange since Safari can release the lock when the tab is
// backgrounded (e.g. the iPad briefly locks) and doesn't restore it
// automatically. Older iPadOS (this dashboard's own iPad is stuck on
// 15.8.x) has no Wake Lock API at all, so fall back to the classic
// NoSleep.js-style trick: a muted, looping, playsinline video keeps iOS
// from dimming/locking the screen even without that API.
let wakeLock = null;
async function requestWakeLock() {{
  try {{
    wakeLock = await navigator.wakeLock.request('screen');
  }} catch (err) {{
    // Unsupported or denied -- the video fallback below covers this.
  }}
}}
if ('wakeLock' in navigator) {{
  requestWakeLock();
  document.addEventListener('visibilitychange', () => {{
    if (document.visibilityState === 'visible') requestWakeLock();
  }});
}} else {{
  const video = document.getElementById('nosleep-video');
  video.play().catch(() => {{
    // Autoplay blocked -- resume on first touch, which iOS always allows.
    document.addEventListener('touchstart', () => video.play(), {{once: true}});
  }});
}}
</script>
</body>
</html>"""
