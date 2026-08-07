"""Renders the cigar-storage dashboard.

Two outputs, both written by `generate_dashboard.py`, same pattern as
home_dashboard/energy_report: `index.html` (page shell embedding an initial
data snapshot so first paint isn't blank) and `data.json` (refetched by the
page's own client-side JS every 60 seconds, applied in place -- no reload).

Unlike home_dashboard, this isn't an always-on kiosk display, so there's
deliberately no PWA manifest/icons, Wake Lock handling, or NoSleep video
here -- none of that was asked for, and adding it would be scope beyond
what a browser-viewed dashboard needs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from cigar_dashboard.govee_history import DEVICE_IDS, DeviceReading, HistoryPoint

BG_COLOR = "#0b0e14"
CARD_COLOR = "#161b26"
TEXT_COLOR = "#f2f4f8"
MUTED_COLOR = "#8b93a7"

# One fixed color per device, used consistently across both charts and any
# per-device legend/swatch -- so "blue" always means Wineador, everywhere
# on the page.
DEVICE_COLORS: dict[str, str] = {
    "TH01": "#4da3ff",
    "TH02": "#f59e0b",
    "TH03": "#34d399",
}


@dataclass(frozen=True)
class DashboardContext:
    generated_at: datetime
    readings: dict[str, DeviceReading]
    humidity_history: dict[str, list[HistoryPoint]] = field(default_factory=dict)
    temp_history: dict[str, list[HistoryPoint]] = field(default_factory=dict)


def _fmt_pct(v: float | None) -> str:
    return f"{v:.0f}%" if v is not None else "--"


def _fmt_temp(v: float | None) -> str:
    return f"{v:.0f}°F" if v is not None else "--"


def _history_dict(history: dict[str, list[HistoryPoint]]) -> dict[str, list[dict]]:
    return {
        device_id: [{"t": p.at_local.isoformat(), "v": p.value} for p in points]
        for device_id, points in history.items()
    }


def _data_dict(ctx: DashboardContext) -> dict:
    return {
        "generated_at": ctx.generated_at.isoformat(),
        "devices": {
            device_id: {
                "label": r.label,
                "temp_f": r.temp_f,
                "humidity_pct": r.humidity_pct,
                "battery_pct": r.battery_pct,
                "color": DEVICE_COLORS[device_id],
            }
            for device_id, r in ctx.readings.items()
        },
        "humidity_history": _history_dict(ctx.humidity_history),
        "temp_history": _history_dict(ctx.temp_history),
    }


def render_data_json(ctx: DashboardContext) -> str:
    return json.dumps(_data_dict(ctx))


def _device_cards_html(ctx: DashboardContext) -> str:
    cards = []
    for device_id in DEVICE_IDS:
        r = ctx.readings.get(device_id)
        color = DEVICE_COLORS[device_id]
        label = r.label if r else device_id
        cards.append(
            f"""<div class="card" style="border-top:3px solid {color}">
  <div class="label">{label}</div>
  <div class="humidity" id="humidity-{device_id}">{_fmt_pct(r.humidity_pct if r else None)}</div>
  <div class="sub">Humidity</div>
  <div class="temp" id="temp-{device_id}">{_fmt_temp(r.temp_f if r else None)}</div>
  <div class="battery" id="battery-{device_id}">Battery {_fmt_pct(r.battery_pct if r else None)}</div>
</div>"""
        )
    return "\n".join(cards)


def render_html(ctx: DashboardContext) -> str:
    initial_data = json.dumps(_data_dict(ctx))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cigar Storage</title>
<style>
:root{{--bg:{BG_COLOR};--card:{CARD_COLOR};--text:{TEXT_COLOR};--muted:{MUTED_COLOR};--r:16px;--gap:16px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);padding:3vh 3vw;display:flex;flex-direction:column;gap:var(--gap)}}
h1{{font-size:min(4vw,28px);font-weight:800}}
.generated-at{{font-size:13px;color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--gap)}}
.card{{background:var(--card);border-radius:var(--r);padding:2.5vh 2vw}}
.card .label{{font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}}
.card .humidity{{font-size:min(6vw,44px);font-weight:800;line-height:1}}
.card .sub{{font-size:12px;color:var(--muted);margin-bottom:10px}}
.card .temp{{font-size:min(3.4vw,24px);font-weight:700}}
.card .battery{{font-size:13px;color:var(--muted);margin-top:6px}}
.chart-card{{background:var(--card);border-radius:var(--r);padding:2vh 2vw}}
.chart-card.humidity-chart svg{{height:26vh}}
.chart-card.temp-chart svg{{height:16vh}}
.chart-card .chart-title{{font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px}}
.chart-card svg{{width:100%;display:block}}
.legend{{display:flex;gap:18px;margin-top:8px;flex-wrap:wrap}}
.legend-item{{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}}
.legend-swatch{{width:10px;height:10px;border-radius:2px;display:inline-block}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div>
  <h1>Cigar Storage</h1>
  <div class="generated-at" id="generated-at"></div>
</div>

<div class="cards">
{_device_cards_html(ctx)}
</div>

<div class="chart-card humidity-chart">
  <div class="chart-title">Humidity -- last 7 days</div>
  <svg id="humidity-svg" viewBox="0 0 600 200" preserveAspectRatio="none"></svg>
  <div class="legend" id="humidity-legend"></div>
</div>

<div class="chart-card temp-chart">
  <div class="chart-title">Temperature -- last 7 days</div>
  <svg id="temp-svg" viewBox="0 0 600 130" preserveAspectRatio="none"></svg>
  <div class="legend" id="temp-legend"></div>
</div>

<script>
const REFRESH_MS = 60000;

function drawMultiSeries(svgEl, legendEl, histories, devices, unitSuffix) {{
  const deviceIds = Object.keys(devices);
  const seriesEntries = deviceIds
    .map(id => [id, histories[id] || []])
    .filter(([, points]) => points.length >= 2);

  legendEl.innerHTML = deviceIds.map(id =>
    `<span class="legend-item"><span class="legend-swatch" style="background:${{devices[id].color}}"></span>${{devices[id].label}}</span>`
  ).join('');

  if (seriesEntries.length === 0) {{
    svgEl.innerHTML = '';
    return;
  }}

  const viewBox = svgEl.viewBox.baseVal;
  const width = viewBox.width, height = viewBox.height;
  const padLeft = 40, padRight = 8, padTop = 10, padBottom = 20;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  // Shared scale across every series, so lines drawn on the same axes are
  // directly comparable -- computed from the union of all points, not
  // per-series (a per-series scale would make e.g. Drybox's tighter band
  // look just as "active" as Wineador's, which would be misleading).
  const allPoints = seriesEntries.flatMap(([, points]) => points);
  const times = allPoints.map(p => new Date(p.t).getTime());
  const values = allPoints.map(p => p.v);
  const minT = Math.min(...times), maxT = Math.max(...times);
  const minV = Math.min(...values), maxV = Math.max(...values);
  const spanT = (maxT - minT) || 1;
  const spanV = (maxV - minV) || 1;
  const xFor = t => padLeft + plotW * ((t - minT) / spanT);
  const yFor = v => padTop + plotH - plotH * ((v - minV) / spanV);
  const timeFmt = t => new Date(t).toLocaleDateString([], {{month: 'short', day: 'numeric'}});

  let svgHtml = '';

  seriesEntries.forEach(([id, points]) => {{
    const color = devices[id] ? devices[id].color : '#4da3ff';
    const pointsAttr = points
      .map(p => xFor(new Date(p.t).getTime()).toFixed(1) + ',' + yFor(p.v).toFixed(1))
      .join(' ');
    svgHtml += `<polyline points="${{pointsAttr}}" fill="none" stroke="${{color}}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  }});

  // y-axis: a gridline + label at the overall min and max.
  [minV, maxV].forEach(v => {{
    const y = yFor(v).toFixed(1);
    svgHtml += `<line x1="${{padLeft}}" y1="${{y}}" x2="${{width - padRight}}" y2="${{y}}" stroke="#2a2f3a" stroke-width="1"/>`;
    svgHtml += `<text x="${{padLeft - 6}}" y="${{y}}" text-anchor="end" dominant-baseline="middle" font-size="11" fill="#8b93a7">${{Math.round(v)}}${{unitSuffix}}</text>`;
  }});

  // x-axis: a date label at the start, middle, and end of the window.
  [
    [minT, 'start'],
    [(minT + maxT) / 2, 'middle'],
    [maxT, 'end'],
  ].forEach(([t, anchor]) => {{
    const x = xFor(t).toFixed(1);
    svgHtml += `<text x="${{x}}" y="${{height - 4}}" text-anchor="${{anchor}}" font-size="11" fill="#8b93a7">${{timeFmt(t)}}</text>`;
  }});

  svgEl.innerHTML = svgHtml;
}}

function applyData(d) {{
  document.getElementById('generated-at').textContent = 'Updated ' + new Date(d.generated_at).toLocaleTimeString([], {{hour: 'numeric', minute: '2-digit'}});

  Object.entries(d.devices || {{}}).forEach(([id, dev]) => {{
    const humidityEl = document.getElementById('humidity-' + id);
    if (humidityEl) humidityEl.textContent = dev.humidity_pct != null ? Math.round(dev.humidity_pct) + '%' : '--';
    const tempEl = document.getElementById('temp-' + id);
    if (tempEl) tempEl.textContent = dev.temp_f != null ? Math.round(dev.temp_f) + '°F' : '--';
    const batteryEl = document.getElementById('battery-' + id);
    if (batteryEl) batteryEl.textContent = 'Battery ' + (dev.battery_pct != null ? Math.round(dev.battery_pct) + '%' : '--');
  }});

  drawMultiSeries(document.getElementById('humidity-svg'), document.getElementById('humidity-legend'), d.humidity_history || {{}}, d.devices || {{}}, '%');
  drawMultiSeries(document.getElementById('temp-svg'), document.getElementById('temp-legend'), d.temp_history || {{}}, d.devices || {{}}, '°');
}}

applyData({initial_data});

async function refreshData() {{
  try {{
    const res = await fetch('data.json', {{cache: 'no-store'}});
    applyData(await res.json());
  }} catch (err) {{
    // Transient fetch failure -- keep showing the last-known-good data.
  }}
}}
setInterval(refreshData, REFRESH_MS);
</script>
</body>
</html>"""
