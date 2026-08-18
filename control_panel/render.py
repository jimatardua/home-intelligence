"""Renders the control panel's static HTML shell.

Unlike the other three pages' render.py, there's no `ReportContext`/data
class here -- nothing about this page's HTML changes between generations
(see generate_page.py). All the live data (thermostat mode/temp) and every
button action come from the browser's own `fetch()` calls to
`/control/api/*` (server.py) at view time, not anything baked in at
generation time. Reuses `site_shared.nav`/`site_shared.theme` exactly the
same way the other three pages do.
"""

from __future__ import annotations

from site_shared import nav, theme

from control_panel.const import (
    HVAC_MODE_LABELS,
    HVAC_MODES,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    ROOM_LABELS,
    TEMPERATURE_STEP,
)


def _mode_buttons_html() -> str:
    buttons = [f'<button class="mode-btn" data-mode="{m}">{HVAC_MODE_LABELS[m]}</button>' for m in HVAC_MODES]
    return "\n    ".join(buttons)


def _blind_buttons_html(room: str) -> str:
    return f"""<button class="blind-btn" data-room="{room}" data-position="100">Open</button>
    <button class="blind-btn" data-room="{room}" data-position="50">Mid</button>
    <button class="blind-btn" data-room="{room}" data-position="0">Close</button>"""


def render_html() -> str:
    room_cards = "\n".join(
        f"""<div class="card">
  <h3>{ROOM_LABELS[room]} Blinds</h3>
  <div class="btn-row">
    {_blind_buttons_html(room)}
  </div>
</div>"""
        for room in ROOM_LABELS
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Control Panel</title>
{theme.render_theme_bootstrap_script()}
<style>
{theme.render_theme_style_block()}
:root{{--r:10px;--gap:14px}}
{nav.NAV_STYLE}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text)}}
.wrap{{max-width:700px;margin:0 auto;padding:var(--gap)}}
header{{margin-bottom:var(--gap)}}
header h1{{font-size:20px;font-weight:700}}
.health-banner{{background:var(--card);border:1px solid var(--warn);border-radius:var(--r);padding:14px 20px;margin-bottom:var(--gap);display:none}}
.health-banner-message{{color:var(--warn);font-weight:700;font-size:14px}}
.card{{background:var(--card);border-radius:var(--r);padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:var(--gap)}}
.card h3{{font-size:14px;font-weight:600;margin-bottom:12px}}
.thermo-info{{font-size:15px;color:var(--muted);margin-bottom:14px}}
.btn-row{{display:flex;gap:8px;flex-wrap:wrap}}
.btn-row button{{flex:1;min-width:80px;padding:14px 10px;border:none;border-radius:8px;background:var(--bg);color:var(--text);font-size:14px;font-weight:600;cursor:pointer}}
.mode-btn.active{{background:var(--accent);color:#fff}}
.temp-adjust{{display:flex;align-items:center;gap:16px;margin-bottom:14px}}
.temp-btn{{width:44px;height:44px;flex:none;border-radius:50%;border:none;background:var(--bg);color:var(--text);font-size:20px;font-weight:700;cursor:pointer}}
#temp-target-value{{font-size:26px;font-weight:700;min-width:64px;text-align:center}}
.blind-btn.pending{{opacity:.6}}
.status-text{{font-size:12px;color:var(--muted);margin-top:8px;min-height:16px}}
</style>
</head>
<body>
<div class="wrap">
{nav.render_nav_html("control")}
{nav.render_swipe_nav_script("control")}
<header>
  <h1>Control Panel</h1>
</header>

<div class="health-banner" id="ha-error-banner">
  <div class="health-banner-message" id="ha-error-message"></div>
</div>

<div class="card">
  <h3>Family Room Thermostat</h3>
  <div class="thermo-info" id="thermo-info">Loading...</div>
  <div class="temp-adjust">
    <button class="temp-btn" id="temp-down">&minus;</button>
    <span id="temp-target-value">--°</span>
    <button class="temp-btn" id="temp-up">+</button>
  </div>
  <div class="btn-row">
    {_mode_buttons_html()}
  </div>
</div>

{room_cards}

<script>
function showHaError(message) {{
  document.getElementById('ha-error-message').textContent = message;
  document.getElementById('ha-error-banner').style.display = 'block';
}}
function clearHaError() {{
  document.getElementById('ha-error-banner').style.display = 'none';
}}

let lastCurrentTemp = null;
let lastTargetTemp = null;

// The Nest is cloud-synced (Google's SDM API), not a local device -- a
// service call returning success only means HA accepted and dispatched
// the request, not that the thermostat has actually confirmed the change
// back yet (commonly a few real seconds of lag). Refreshing immediately
// after a POST was racing that lag and reading back the *old* value,
// undoing the button's own visible effect -- confirmed live: it took
// exactly two presses to register one degree of change, every time.
// Fix: update the display optimistically from what we just successfully
// asked for, and only re-fetch after a delay long enough for the cloud
// round trip to have actually landed (a genuine failure -- the request
// silently not taking effect on the real device -- still gets caught by
// this delayed refresh, or the periodic poll below, just not instantly).
const REFRESH_AFTER_ACTION_MS = 4000;

function renderThermoInfo() {{
  const cur = lastCurrentTemp != null ? Math.round(lastCurrentTemp) + '°' : '--';
  const tgt = lastTargetTemp != null ? lastTargetTemp + '°' : '--';
  document.getElementById('thermo-info').textContent = cur + ' now, set to ' + tgt;
  document.getElementById('temp-target-value').textContent = tgt;
}}

async function refreshThermostat() {{
  try {{
    const resp = await fetch('/control/api/thermostat');
    if (!resp.ok) {{
      const body = await resp.json().catch(() => ({{}}));
      showHaError(body.message || ('Thermostat read failed (' + resp.status + ')'));
      return;
    }}
    clearHaError();
    const d = await resp.json();
    lastCurrentTemp = d.current_temp;
    lastTargetTemp = d.target_temp != null ? Math.round(d.target_temp) : null;
    renderThermoInfo();
    document.querySelectorAll('.mode-btn').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-mode') === d.mode);
    }});
  }} catch (e) {{
    showHaError('Could not reach the control panel server.');
  }}
}}

async function adjustTargetTemp(delta) {{
  if (lastTargetTemp == null) return;
  const next = Math.min({MAX_TEMPERATURE}, Math.max({MIN_TEMPERATURE}, lastTargetTemp + delta));
  if (next === lastTargetTemp) return;
  try {{
    const resp = await fetch('/control/api/thermostat', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{temperature: next}})
    }});
    if (!resp.ok) {{
      const body = await resp.json().catch(() => ({{}}));
      showHaError(body.message || ('Temperature change failed (' + resp.status + ')'));
      return;
    }}
    clearHaError();
    lastTargetTemp = next;
    renderThermoInfo();
  }} catch (e) {{
    showHaError('Could not reach the control panel server.');
    return;
  }}
  setTimeout(refreshThermostat, REFRESH_AFTER_ACTION_MS);
}}

document.getElementById('temp-down').addEventListener('click', function() {{ adjustTargetTemp(-{TEMPERATURE_STEP}); }});
document.getElementById('temp-up').addEventListener('click', function() {{ adjustTargetTemp({TEMPERATURE_STEP}); }});

document.querySelectorAll('.mode-btn').forEach(function(b) {{
  b.addEventListener('click', async function() {{
    const mode = b.getAttribute('data-mode');
    b.classList.add('pending');
    try {{
      const resp = await fetch('/control/api/thermostat', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{mode: mode}})
      }});
      if (!resp.ok) {{
        const body = await resp.json().catch(() => ({{}}));
        showHaError(body.message || ('Mode change failed (' + resp.status + ')'));
      }} else {{
        clearHaError();
        document.querySelectorAll('.mode-btn').forEach(function(btn) {{
          btn.classList.toggle('active', btn === b);
        }});
      }}
    }} catch (e) {{
      showHaError('Could not reach the control panel server.');
    }}
    b.classList.remove('pending');
    setTimeout(refreshThermostat, REFRESH_AFTER_ACTION_MS);
  }});
}});

document.querySelectorAll('.blind-btn').forEach(function(b) {{
  b.addEventListener('click', async function() {{
    const room = b.getAttribute('data-room');
    const statusEl = b.closest('.card').querySelector('.status-text') || (function() {{
      const el = document.createElement('div');
      el.className = 'status-text';
      b.closest('.card').appendChild(el);
      return el;
    }})();
    b.classList.add('pending');
    statusEl.textContent = 'Sending...';
    try {{
      const resp = await fetch('/control/api/blinds/' + room, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{position: parseInt(b.getAttribute('data-position'), 10)}})
      }});
      if (!resp.ok) {{
        const body = await resp.json().catch(() => ({{}}));
        statusEl.textContent = 'Failed: ' + (body.message || resp.status);
      }} else {{
        statusEl.textContent = 'Sent.';
      }}
    }} catch (e) {{
      statusEl.textContent = 'Could not reach the control panel server.';
    }}
    b.classList.remove('pending');
    setTimeout(function() {{ statusEl.textContent = ''; }}, 4000);
  }});
}});

refreshThermostat();
setInterval(refreshThermostat, 30000);
</script>
</div>
</body>
</html>"""
