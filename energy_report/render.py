"""Renders the RMP cost-comparison report as a static HTML page.

Mirrors ~/Developer/infrastructure's `generate_local_bw_dashboard.py`
conventions exactly (same CSS custom properties, KPI-card grid, dark header
bar, tab-button pattern, CDN Chart.js pinned with SRI, meta-refresh instead
of JS polling) so this fits the same visual language as the existing
bandwidth dashboards, without sharing a template module (matching that
project's own precedent -- no shared template code between similar
generator scripts there either).

Unlike the bandwidth dashboard (which re-fetches/re-scales the same charts
across client-side view switches), this report's numbers are entirely
precomputed server-side each run -- the "tabs" here just show/hide
pre-rendered blocks; there is no client-side recomputation of dollar
amounts at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json

# Pinned exactly to match the reference bandwidth dashboards -- same CDN
# versions and SRI hashes, copied verbatim so a browser that already
# cached them for those pages doesn't need a second download.
_CHARTJS_SCRIPT = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" '
    'integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" '
    'crossorigin="anonymous"></script>'
)
_CHARTJS_DATE_ADAPTER_SCRIPT = (
    '<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0" '
    'integrity="sha384-cVMg8E3QFwTvGCDuK+ET4PD341jF3W8nO1auiXfuZNQkzbUUiBGLsIQUE+b1mxws" '
    'crossorigin="anonymous"></script>'
)


@dataclass(frozen=True)
class DailyBreakdown:
    d: date
    ac_kwh: float
    ev_kwh: float
    other_kwh: float
    onpeak_kwh: float
    offpeak_kwh: float
    hours_present: int
    hours_expected: int


@dataclass(frozen=True)
class LeverRow:
    name: str
    annual_impact_dollars: float | None
    pending: bool
    note: str


@dataclass(frozen=True)
class ReportContext:
    generated_at: datetime
    data_as_of: datetime | None
    day_count: int
    date_range_start: date | None
    date_range_end: date | None
    hour_coverage_pct: float
    seasons_observed: frozenset[str]
    maturity_tier: str  # "insufficient" | "early" | "seasonal"

    observed_schedule1_cost: float
    observed_tou_cost: float

    # None when the maturity gate hasn't cleared for that season/tier yet.
    summer_monthly_projection: tuple[float, float] | None
    summer_annual_projection: tuple[float, float] | None
    winter_available: bool

    sensitivity_rows: list[LeverRow]
    daily_breakdown: list[DailyBreakdown]
    tariff_effective_date: date
    guarantee_note: str = (
        "RMP guarantees TOU costs won't exceed standard-plan costs by more than "
        "10% in the first 12 months of enrollment (credited back) -- a real "
        "safety net not reflected in the numbers above."
    )


def _fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _fmt_maybe_money(v: float | None) -> str:
    return _fmt_money(v) if v is not None else "N/A"


def _maturity_label(tier: str) -> str:
    return {
        "insufficient": "Insufficient data for any projection yet",
        "early": "Early signal -- single season only",
        "seasonal": "Seasonal comparison available",
    }.get(tier, tier)


def _sensitivity_table_html(rows: list[LeverRow]) -> str:
    body_rows = []
    for r in rows:
        if r.pending:
            value_html = f'<span class="muted">{r.note}</span>'
        elif r.annual_impact_dollars is None:
            value_html = f'<span class="muted">{r.note}</span>'
        else:
            cls = "impact-pos" if r.annual_impact_dollars >= 0 else "impact-neg"
            value_html = f'<span class="{cls}">{_fmt_money(r.annual_impact_dollars)}</span>'
        body_rows.append(f"<tr><td>{r.name}</td><td>{value_html}</td></tr>")
    return (
        '<table class="sensitivity"><thead><tr><th>Change</th><th>Annual impact</th></tr>'
        f"</thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _chart_series(daily: list[DailyBreakdown]) -> dict:
    labels = [d.d.isoformat() for d in daily]
    return {
        "labels": labels,
        "ac": [round(d.ac_kwh, 2) for d in daily],
        "ev": [round(d.ev_kwh, 2) for d in daily],
        "other": [round(d.other_kwh, 2) for d in daily],
        "onpeak": [round(d.onpeak_kwh, 2) for d in daily],
        "offpeak": [round(d.offpeak_kwh, 2) for d in daily],
        "coverage_pct": [
            round(100 * d.hours_present / d.hours_expected, 1) if d.hours_expected else None
            for d in daily
        ],
    }


def render_report(ctx: ReportContext) -> str:
    data_as_of_str = ctx.data_as_of.strftime("%Y-%m-%d %H:%M %Z") if ctx.data_as_of else "no data yet"
    date_range_str = (
        f"{ctx.date_range_start.isoformat()} to {ctx.date_range_end.isoformat()}"
        if ctx.date_range_start and ctx.date_range_end
        else "no data yet"
    )
    seasons_str = ", ".join(sorted(ctx.seasons_observed)) if ctx.seasons_observed else "none"

    diff = ctx.observed_tou_cost - ctx.observed_schedule1_cost
    if diff > 0:
        diff_heading = "Estimated TOU Penalty"
        diff_class = "impact-neg"
        diff_sub = "TOU would have cost this much more over this window"
    elif diff < 0:
        diff_heading = "Estimated TOU Savings"
        diff_class = "impact-pos"
        diff_sub = "TOU would have saved this much over this window"
    else:
        diff_heading = "No Difference"
        diff_class = ""
        diff_sub = "TOU and standard costs were identical over this window"

    summer_monthly = ctx.summer_monthly_projection
    summer_annual = ctx.summer_annual_projection

    winter_projection_note = (
        "Insufficient winter data -- winter costs will appear once October-May "
        "usage has been collected."
        if not ctx.winter_available
        else ""
    )

    series = _chart_series(ctx.daily_breakdown)
    sensitivity_html = _sensitivity_table_html(ctx.sensitivity_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="3600">
<title>RMP: Standard vs. Time-of-Use</title>
{_CHARTJS_SCRIPT}
{_CHARTJS_DATE_ADAPTER_SCRIPT}
<style>
:root{{--bg:#f0f2f5;--card:#fff;--header:#1a1a2e;--text:#212529;--muted:#6c757d;--gap:14px;--r:10px;--accent:#2563eb}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text)}}
.wrap{{max-width:1000px;margin:0 auto;padding:var(--gap)}}
header{{background:var(--header);color:#fff;padding:16px 24px;border-radius:var(--r);margin-bottom:var(--gap);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
header h1{{font-size:18px;font-weight:700}}
header .meta{{font-size:12px;color:rgba(255,255,255,.55)}}
.banner{{background:var(--card);border-radius:var(--r);padding:14px 20px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:var(--gap);font-size:13px}}
.banner .tier{{font-weight:700;color:var(--accent)}}
.kpi-row{{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--gap);margin-bottom:var(--gap)}}
.kpi{{background:var(--card);border-radius:var(--r);padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.08);border-top:4px solid var(--accent)}}
.kpi.tou{{--accent:#7c3aed}}.kpi.diff{{--accent:#d97706}}
.kpi-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px}}
.kpi-value{{font-size:26px;font-weight:800;margin-bottom:2px}}
.kpi-sub{{font-size:12px;color:var(--muted);margin-top:4px}}
.tabs{{display:flex;gap:2px;margin-bottom:var(--gap)}}
.tab{{padding:7px 18px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;background:#e2e6ea;color:var(--muted);border:none}}
.tab.active{{background:var(--header);color:#fff}}
.tabpanel{{display:none}}
.tabpanel.active{{display:block}}
.card{{background:var(--card);border-radius:var(--r);padding:18px 22px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:var(--gap)}}
.card h3{{font-size:14px;font-weight:600;margin-bottom:14px}}
.chart-wrap{{position:relative;height:260px}}
table.sensitivity{{width:100%;border-collapse:collapse;font-size:13px}}
table.sensitivity th{{text-align:left;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;padding-bottom:8px;border-bottom:1px solid #e2e6ea}}
table.sensitivity td{{padding:9px 0;border-bottom:1px solid #f0f2f5}}
table.sensitivity th:last-child,table.sensitivity td:last-child{{text-align:right}}
table.sensitivity td:last-child{{font-weight:700}}
.impact-pos{{color:#16794f}}
.impact-neg{{color:#c0392b}}
.muted{{color:var(--muted);font-weight:400 !important}}
footer{{text-align:center;font-size:11px;color:var(--muted);padding:10px 0}}
@media(max-width:500px){{.kpi-row{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Rocky Mountain Power: Standard vs. Time-of-Use</h1>
  <span class="meta">Data as of {data_as_of_str} &nbsp;·&nbsp; <a href="." style="color:rgba(255,255,255,.6)">&#8635; refresh</a></span>
</header>

<div class="banner">
  <span class="tier">{_maturity_label(ctx.maturity_tier)}</span> &nbsp;·&nbsp;
  {ctx.day_count} day(s) of data ({date_range_str}) &nbsp;·&nbsp;
  {ctx.hour_coverage_pct:.0f}% hour coverage &nbsp;·&nbsp;
  season(s) observed: {seasons_str} &nbsp;·&nbsp;
  tariff effective {ctx.tariff_effective_date.isoformat()}
</div>

<div class="kpi-row">
  <div class="kpi standard">
    <div class="kpi-label">Standard plan (observed)</div>
    <div class="kpi-value">{_fmt_money(ctx.observed_schedule1_cost)}</div>
    <div class="kpi-sub">Exact cost for the hours of data collected so far</div>
  </div>
  <div class="kpi tou">
    <div class="kpi-label">Time-of-Use (observed)</div>
    <div class="kpi-value">{_fmt_money(ctx.observed_tou_cost)}</div>
    <div class="kpi-sub">Same hours, TOU rates</div>
  </div>
  <div class="kpi diff">
    <div class="kpi-label">{diff_heading}</div>
    <div class="kpi-value {diff_class}">{_fmt_money(abs(diff))}</div>
    <div class="kpi-sub">{diff_sub}</div>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="setTab('observed',this)">Observed</button>
  <button class="tab" onclick="setTab('monthly',this)">Monthly projection</button>
  <button class="tab" onclick="setTab('annual',this)">Annual projection</button>
</div>

<div class="card">
  <div id="tab-observed" class="tabpanel active">
    <p>Exact cost for the {ctx.day_count} day(s) of data actually collected, zero scaling.
    This is the only number that's unconditionally honest at any data volume.</p>
  </div>
  <div id="tab-monthly" class="tabpanel">
    {"<p>Standard: " + _fmt_money(summer_monthly[0]) + " &nbsp;·&nbsp; TOU: " + _fmt_money(summer_monthly[1]) + " <span class='muted'>(summer rates, scaled from " + str(ctx.day_count) + " observed day(s) -- early projection)</span></p>" if summer_monthly else "<p class='muted'>" + (winter_projection_note or "Not enough data yet for a monthly projection.") + "</p>"}
  </div>
  <div id="tab-annual" class="tabpanel">
    {"<p>Standard: " + _fmt_money(summer_annual[0]) + " &nbsp;·&nbsp; TOU: " + _fmt_money(summer_annual[1]) + " <span class='muted'>(summer-only projection -- winter months not yet represented)</span></p>" if summer_annual else "<p class='muted'>" + (winter_projection_note or "Not enough data yet for an annual projection.") + "</p>"}
    {"<p class='muted'>" + winter_projection_note + "</p>" if summer_annual and winter_projection_note else ""}
  </div>
</div>

<div class="card">
  <h3>Sensitivity: what would each change be worth?</h3>
  {sensitivity_html}
  <p class="muted" style="margin-top:10px;font-size:12px">Each row is independent -- computed holding everything else at its actually-observed value, not additive. Best-case/upper-bound estimates, not promises.</p>
</div>

<div class="card">
  <h3>Usage breakdown (A/C · EV charging · other/baseline)</h3>
  <div class="chart-wrap"><canvas id="disaggChart"></canvas></div>
</div>

<div class="card">
  <h3>On-peak vs. off-peak usage</h3>
  <div class="chart-wrap"><canvas id="peakChart"></canvas></div>
</div>

<footer>
  {ctx.guarantee_note}<br>
  Billing-month tiering approximated with calendar-month boundaries (actual RMP billing-cycle start date unknown).
  A/C draw is a nameplate-derived estimate (~5.8 kW), not measured.
  Generated {ctx.generated_at.strftime('%Y-%m-%d %H:%M %Z')}.
</footer>
</div>
<script>
const SERIES = {json.dumps(series)};

function setTab(name, btn) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tabpanel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}}

const commonOpts = {{
  responsive: true, maintainAspectRatio: false, animation: false,
  interaction: {{mode: 'index', intersect: false}},
  plugins: {{
    tooltip: {{callbacks: {{label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y}} kWh`}}}}
  }},
  scales: {{
    x: {{stacked: true, grid: {{display: false}}, ticks: {{font: {{size: 10}}}}}},
    y: {{stacked: true, beginAtZero: true, grid: {{color: 'rgba(0,0,0,0.04)'}}, ticks: {{font: {{size: 10}}, callback: v => v + ' kWh'}}}}
  }}
}};

const disaggOpts = {{
  ...commonOpts,
  plugins: {{
    ...commonOpts.plugins,
    tooltip: {{
      callbacks: {{
        label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y}} kWh`,
        footer: items => `Total: ${{items.reduce((sum, item) => sum + item.parsed.y, 0).toFixed(2)}} kWh`
      }}
    }}
  }}
}};

new Chart(document.getElementById('disaggChart'), {{
  type: 'bar',
  data: {{
    labels: SERIES.labels,
    datasets: [
      {{label: 'A/C (estimated)', data: SERIES.ac, backgroundColor: '#d97706'}},
      {{label: 'EV charging', data: SERIES.ev, backgroundColor: '#7c3aed'}},
      {{label: 'Other/baseline', data: SERIES.other, backgroundColor: '#94a3b8'}},
    ]
  }},
  options: disaggOpts
}});

new Chart(document.getElementById('peakChart'), {{
  type: 'bar',
  data: {{
    labels: SERIES.labels,
    datasets: [
      {{label: 'On-peak (6-10pm weekdays)', data: SERIES.onpeak, backgroundColor: '#c0392b'}},
      {{label: 'Off-peak', data: SERIES.offpeak, backgroundColor: '#2563eb'}},
    ]
  }},
  options: commonOpts
}});
</script>
</body>
</html>"""
