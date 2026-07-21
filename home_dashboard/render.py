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

from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass(frozen=True)
class ForecastPeriodView:
    name: str
    is_daytime: bool
    temperature_f: int
    short_forecast: str
    precip_probability_pct: int


@dataclass(frozen=True)
class DashboardContext:
    generated_at: datetime

    outdoor_temp_f: float | None
    outdoor_humidity_pct: float | None
    condition: str | None  # prettified NWS condition, e.g. "Partly Cloudy"

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


def _data_dict(ctx: DashboardContext) -> dict:
    return {
        "generated_at": ctx.generated_at.isoformat(),
        "outdoor_temp_f": ctx.outdoor_temp_f,
        "outdoor_humidity_pct": ctx.outdoor_humidity_pct,
        "condition": _prettify_condition(ctx.condition),
        "indoor_temp_f": ctx.indoor_temp_f,
        "indoor_humidity_pct": ctx.indoor_humidity_pct,
        "hvac_mode": ctx.hvac_mode,
        "hvac_action": ctx.hvac_action,
        "thermostat_label": _thermostat_label(ctx),
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
            }
            for p in ctx.forecast_periods
        ],
    }


def render_data_json(ctx: DashboardContext) -> str:
    return json.dumps(_data_dict(ctx))


def render_html(ctx: DashboardContext) -> str:
    initial_data = json.dumps(_data_dict(ctx))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Home</title>
<style>
:root{{--bg:#0b0e14;--card:#161b26;--text:#f2f4f8;--muted:#8b93a7;--accent:#4da3ff;--r:16px;--gap:16px}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%;overflow:hidden}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;padding:2vh 2vw;gap:var(--gap)}}
.hero{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--gap)}}
.clock{{font-size:min(14vw,120px);font-weight:800;line-height:1;letter-spacing:-2px}}
.date{{font-size:min(3vw,24px);color:var(--muted);margin-top:4px}}
.outdoor{{text-align:right}}
.outdoor .temp{{font-size:min(10vw,90px);font-weight:800;line-height:1}}
.outdoor .condition{{font-size:min(3vw,22px);color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--gap)}}
.card{{background:var(--card);border-radius:var(--r);padding:3vh 2vw}}
.card .label{{font-size:min(2vw,13px);color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}}
.card .value{{font-size:min(5vw,40px);font-weight:700}}
.card .sub{{font-size:min(2.2vw,15px);color:var(--muted);margin-top:6px}}
.forecast{{background:var(--card);border-radius:var(--r);padding:2vh 2vw;display:flex;justify-content:space-between;gap:8px}}
.period{{flex:1;text-align:center;display:flex;flex-direction:column;justify-content:flex-start;gap:4px}}
.period .name{{font-size:min(2.2vw,15px);color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.period .temp{{font-size:min(4vw,32px);font-weight:700}}
.period .cond{{font-size:min(2vw,13px);color:var(--muted)}}
.period .rain{{font-size:min(2vw,13px);color:var(--accent);font-weight:600}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}.forecast{{flex-wrap:wrap}}}}
</style>
</head>
<body>

<div class="hero">
  <div>
    <div class="clock" id="clock">--:--</div>
    <div class="date" id="date"></div>
  </div>
  <div class="outdoor">
    <div class="temp" id="outdoor-temp">--</div>
    <div class="condition" id="outdoor-condition"></div>
  </div>
</div>

<div class="cards">
  <div class="card">
    <div class="label">Indoor</div>
    <div class="value" id="indoor-temp">--</div>
    <div class="sub" id="thermostat-sub"></div>
  </div>
  <div class="card">
    <div class="label">Sun</div>
    <div class="value" id="sun-value" style="font-size:min(4vw,32px)">--</div>
    <div class="sub" id="sun-sub"></div>
  </div>
  <div class="card">
    <div class="label">A/C + EV Today (est.)</div>
    <div class="value" id="usage-value">--</div>
    <div class="sub">Estimate of these two loads only, not total house usage</div>
  </div>
</div>

<div class="forecast" id="forecast"></div>

<script>
const REFRESH_MS = 60000;

function applyData(d) {{
  document.getElementById('outdoor-temp').textContent = d.outdoor_temp_f != null ? Math.round(d.outdoor_temp_f) + '°' : '--';
  document.getElementById('outdoor-condition').textContent = d.condition || '';

  document.getElementById('indoor-temp').textContent = d.indoor_temp_f != null ? Math.round(d.indoor_temp_f) + '°' : '--';
  const hvac = d.hvac_action && d.hvac_action !== 'off' ? d.hvac_action : (d.hvac_mode || 'off');
  document.getElementById('thermostat-sub').textContent = 'Set to ' + d.thermostat_label + ' (' + hvac + ')';

  document.getElementById('sun-value').textContent = d.sunrise + ' / ' + d.sunset;
  document.getElementById('sun-sub').textContent = 'Sunrise / Sunset';

  const usageTotal = (d.usage_today_ac_kwh || 0) + (d.usage_today_ev_kwh || 0);
  document.getElementById('usage-value').textContent = usageTotal.toFixed(1) + ' kWh';

  const forecastEl = document.getElementById('forecast');
  forecastEl.innerHTML = '';
  (d.forecast || []).forEach(p => {{
    const div = document.createElement('div');
    div.className = 'period';
    const rainHtml = p.precip_probability_pct > 0 ? `<div class="rain">${{p.precip_probability_pct}}% rain</div>` : '';
    div.innerHTML = `<div class="name">${{p.name}}</div><div class="temp">${{p.temperature_f}}°</div><div class="cond">${{p.short_forecast}}</div>${{rainHtml}}`;
    forecastEl.appendChild(div);
  }});
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
// automatically.
let wakeLock = null;
async function requestWakeLock() {{
  try {{
    wakeLock = await navigator.wakeLock.request('screen');
  }} catch (err) {{
    // Unsupported or denied -- nothing else to do on older iPadOS versions.
  }}
}}
if ('wakeLock' in navigator) {{
  requestWakeLock();
  document.addEventListener('visibilitychange', () => {{
    if (document.visibilityState === 'visible') requestWakeLock();
  }});
}}
</script>
</body>
</html>"""
