# Control panel: thermostat mode + blind position

The 4th dashboard page (`/control/`), and the first thing in this project
that *writes* to Home Assistant -- every other package only ever reads the
recorder database.

## Why this exists

The user already had HA's own "expanded" thermostat control and asked for
just the same functionality (basic info + off/cool/heat mode) folded into
this project's dashboards for convenience -- "having it in one app is
very convenient," not a replacement for HA's own UI. The blind controls
mirror what HA's own cover card already does with its three buttons
(up/stop/down), except aggregated per room instead of per blind, since
that's how they're actually used.

## Real findings from building this (not assumptions)

- **The 7 blind entities**, found via HA's own registries rather than
  guessed: `cover.office_1`/`_2`/`_3`/`_4` (area `office`) and
  `cover.dining_left`/`_middle`/`_right` (area `dining`), all on the
  `neosmartblinds` integration. `supported_features=191` confirms
  `SET_POSITION` is supported.
- **The exact service-call quirk this design is built around, confirmed
  live from both directions** -- the user's own report of HA's UI
  ("after using the mid button, the up button stays greyed out until you
  fully close then fully open") and a live test against the real API,
  hitting the identical thing: `cover.set_cover_position` works correctly
  the *first* time from a fully-open state (100 -> 50 landed exactly
  where the physical "stop" button does), but repeated
  `set_cover_position` calls after that silently no-op (empty response,
  no state change) -- while `cover.open_cover`/`cover.close_cover` work
  reliably every time. **This is why `server.py` uses the dedicated
  services for the 0%/100% buttons and `set_cover_position` only for
  mid** (`const.py`'s `COVER_POSITION_SERVICE`/`COVER_MID_POSITION`) --
  not because it's simpler, but because it's the only combination
  confirmed to actually work repeatedly.
- **No cover position is ever tracked or displayed**, deliberately -- the
  user's own reasoning, independently confirming the same live finding:
  HA's own tracked position for these covers is a software estimate with
  no real physical feedback (RF-controlled blind motors, no position
  sensor), and it visibly desyncs from reality after using "mid" (see
  above). Displaying a "current state" here would be actively misleading,
  not just unnecessary.
- **The thermostat is `climate.family_room_family_room`**, confirmed
  live (`state=cool`, `current_temperature=75`, `temperature=77`).
  `hvac_modes` isn't in recorder history (HA excludes it as static
  config), so the mode list is what the user explicitly confirmed rather
  than read from history: **off, cool, heat only** -- `heat_cool` is
  deliberately excluded (never used, and needs two setpoints instead of
  one, real added complexity for a mode nobody wants).

## Target temperature (+/-)

Added right after the first live pass, once mode-only turned out to be
missing the obvious other control -- a +/- pair around the target-temp
display, `climate.set_temperature`. Single setpoint only, same
`heat_cool`-excluded reasoning as the mode buttons above applies here too
(a low/high range would need two numbers, not one). Step size and the
0-90/50 sanity bounds live in `const.py`
(`TEMPERATURE_STEP`/`MIN_TEMPERATURE`/`MAX_TEMPERATURE`) -- the bounds are
a guard against an obviously-wrong value (e.g. a stray digit), not an
attempt to enforce the thermostat's real min/max, which HA/the Nest
integration itself already does and will reject on its own if violated.
The client tracks the last-fetched target temp and computes `+/- step`
from that rather than re-deriving it, same pattern the blinds buttons use
for "what room am I acting on."

**Real bug, found live and fixed the same day**: it took exactly two
presses to register one degree of change, every time -- confirmed by the
user, who'd already ruled out a focus/click-registration issue by
deliberately clicking elsewhere on the page first. Root cause: the Nest
is cloud-synced (Google's SDM API), not a local device -- `climate.set_temperature`
returning success only means HA accepted and dispatched the request, not
that the thermostat has confirmed the change back yet (a real few-second
round trip). The original code called `refreshThermostat()` immediately
after every successful POST, which raced that lag and read back the
*old* value, undoing the button's own visible effect until the next
press happened to land after the cloud had caught up. Same underlying
bug affected the mode buttons too, just less noticeably (a color flip
eventually happening is less jarring than a specific number not moving).
**Fixed by updating the display optimistically** from what was just
successfully requested, and only re-fetching after a delay
(`REFRESH_AFTER_ACTION_MS`, 4s) long enough for the round trip to have
actually landed -- that delayed refresh (plus the existing 30s periodic
poll) still catches a genuine failure, just not instantly. One small
residual case, judged not worth the added complexity to close: if the
30-second periodic poll happens to fire during that few-second cloud-lag
window right after a click, it could transiently overwrite the
optimistic value with a still-stale one -- self-corrects on the next
poll 30s later, and is far rarer than the original always-reproducible
bug it replaced.

## Architecture

```
control_panel/
  const.py        -- entity IDs, HVAC modes, room->cover mapping, the
                      position->service mapping described above
  ha_client.py     -- the only thing that ever holds HA_TOKEN or talks to
                      HA directly. Two distinct exceptions
                      (HomeAssistantUnreachable / HomeAssistantError) so
                      the page can tell "HA is down" from "HA got the
                      request but something downstream failed" -- both
                      have now happened for real in this project (HA
                      itself was down for ~47 min once; the blind RF hub
                      timed out once during testing today)
  server.py        -- small Flask app, binds 127.0.0.1 only. Routes:
                      GET/POST /control/api/thermostat,
                      POST /control/api/blinds/<room>
  render.py        -- static HTML shell (site_shared nav/theme, same as
                      the other 3 pages) -- no server-rendered data class
                      unlike the other pages; all live data comes from
                      the browser's own fetch() calls at view time
  generate_page.py -- writes the shell once; NOT cron'd, unlike the other
                      3 pages -- nothing about the rendered HTML changes
                      between runs
  systemd/control-panel.service
  deploy.sh
```

### Token handling

`/etc/home-intelligence-control-panel.env` (`jramsey:jramsey`, `chmod 600`,
`HA_TOKEN=...`) -- a long-lived HA access token the user created and
pasted directly, stored the same way `/etc/govee-collector.env` already
handles the MQTT password. `server.py`'s systemd unit loads it via
`EnvironmentFile=`; the token never reaches the browser, never appears in
any request the client makes, and is only ever read by `ha_client.py`.

### Why Flask, and why its dev server

`python3-flask` (2.2.2-3) and `python3-requests` (2.28.1) were already
installed on domus -- no new package needed. Runs via Flask's own
built-in server (`app.run()`), not a production WSGI server like
gunicorn -- a deliberate simplification for what's genuinely a low-traffic,
localhost-only, single-user internal tool (a handful of button presses a
day), not a public-facing service. `debug=False` (the default, left
unset rather than explicitly disabled) -- the security-relevant one,
since Werkzeug's debugger would otherwise be a real risk. Worth
revisiting only if this ever needs to handle real concurrent load, which
nothing about its actual use case suggests it will.

### Why no cron, unlike the other 3 pages

`generate_page.py` writes the static shell once at deploy time. The
other three pages regenerate every 2 hours/minutes because their content
*is* a snapshot of historical data. This page has no server-rendered data
at all -- the shell is identical every time it's generated, and all the
live content (thermostat state) comes from the browser's own `fetch()`
calls when the page is actually open. Re-run `generate_page.py` only if
`render.py` itself changes.

### nginx / `ha-proxy`

Two new location blocks (one static-file alias like the other 3 pages,
one reverse proxy like the existing HA catch-all, just a different local
port) -- see `deploy.sh` for the exact blocks. `ha-proxy` runs
`--network host` (confirmed via `docker inspect`), so the new backend
process needs **no new bind mount** to become reachable from nginx --
only the new page's static-output directory does, which is the one new
`-v` line in the container recreate (same pattern already done twice for
`cigar_dashboard`/`energy_report`).

## Verification

- 31 new tests (`control_panel/tests/`) -- `render.py` content assertions,
  and `ha_client.py`/`server.py` with all HTTP calls mocked (no real
  token or live calls needed to test), covering: correct entity/service
  per button (especially the open/close-vs-set_position split), input
  validation, and both HA-unreachable and HA-error paths surfacing as
  distinct non-500 responses. `site_shared`'s suite extended for the 4th
  `PAGES` entry. 259 tests passing across all five packages.
- `node --check` on every extracted `<script>` block, same method used
  for every prior page.
- Deployed and confirmed live end-to-end through the full public path
  (browser -> nginx -> Flask backend -> HA -> back):
  `curl https://domus.ardua.com/control/api/thermostat` returns real,
  current thermostat data.
- iOS Simulator: loaded `/control/` on a booted iPad, confirmed the nav
  row is hidden (matching the other 3 pages) and swipe navigation works
  correctly with a 4th page in the chain (Control <-> Energy Report
  confirmed both directions). **Deliberately did not tap any of the
  actual mode/blind buttons in the simulator** -- those fire real
  commands against the real thermostat and real blinds, which shouldn't
  happen unattended/automated. The single-blind live test that validated
  the `set_cover_position` behavior (see above) was done directly against
  the API with the user watching and confirming the physical result, not
  through this page's UI.

## Known risks / things not verified

- **Blind buttons confirmed live by the user through the real page** --
  Office and Dining both tested; behaves correctly, subject to the RF
  hub's own occasional flakiness (see below), which the user confirmed is
  a known, pre-existing limitation of the physical hardware/native app
  too, not something to fix from this project's side.
- **Thermostat mode buttons and the temperature +/- pair have not been
  pressed for real yet** -- temperature adjustment specifically was added
  after the blind testing above, so it's untested end-to-end through the
  actual page. Worth doing once, deliberately.
- **No guaranteed backup reserve or confirmation step** -- every button
  fires immediately on tap, no "are you sure." Given the confirmed-low
  stakes (blinds and a thermostat, not anything safety-critical) this is
  a deliberate simplicity choice, not an oversight, but worth reconsidering
  if a mis-tap ever turns out to be annoying in practice.
- **The blind hub's occasional flakiness is real and confirmed, not
  theoretical** -- a `TimeoutError` was hit once during earlier testing,
  and separately, live user testing of the office room button hit a
  partial-command case (only 3 of 4 blinds moved on one press) and a
  reported timeout that still ended up moving the blind anyway. The user
  confirmed this matches known, pre-existing behavior from HA's own UI
  and the native app -- a physical RF-hub limitation, not something to
  fix from this project's side. The page surfaces failures as an error
  message rather than hiding them, but there's no retry logic --
  pressing the button again is the current (and, per the user, the
  actually-correct) mitigation.
