# Cigar storage monitoring: Govee H5075 BLE sensors -> MQTT -> dashboard

Three Govee H5075 Bluetooth LE thermo-hygrometers monitor cigar storage
environment: `TH01` in a Whynter wineador (primary storage), `TH02` in an
old wooden humidor repurposed as a "drybox," `TH03` loose on a desk
(ambient reference). A dedicated Raspberry Pi, `mrteeny.ardua.lan`, sits
permanently in the office (BLE range of all three) and scans continuously;
Home Assistant itself runs on `domus`, out of BLE range of the sensors.

## Why this exists

Same underlying motivation as the home dashboard and TOU report: once real
sensors exist, purpose-built visibility beats manually checking three
separate physical dial hygrometers. Humidity is the metric that actually
matters for cigar storage, so it's visually emphasized; temperature and
battery are tracked too but secondary.

## Architecture

```
Govee H5075 sensors (BLE advertisements)
        |
   mrteeny (govee_collector, systemd service, User=jramsey)
        |  MQTT publish (retained, QoS 1) -- state + HA discovery config
        v
   Mosquitto broker (HA add-on, core_mosquitto, on domus)
        |  HA's MQTT integration, discovery on by default
        v
   Home Assistant (12 sensor entities: temp/humidity/battery/signal
   strength x 3 devices, grouped as 3 HA "devices")
        |  recorder DB (same SQLite recorder every other package here reads)
        v
   cigar_dashboard (cron every 2 min on domus, reads energy_report.ha_recorder)
        |
        v
   https://domus.ardua.com/cigars/ (static HTML + data.json, client refetch 60s)
```

## Why MQTT, not the SSH-forced-command pattern

The pfSense ARP-presence bridge earlier in this project used a dedicated
SSH account with a forced `command=` in `authorized_keys` -- the only
reasonable option there, since pfSense is a locked-down firewall appliance
that isn't going to run an MQTT client. mrteeny is a general-purpose Debian
box under full control, so MQTT (the standard, idiomatic HA pattern for
"remote device pushes telemetry") is the better fit: lower latency (push,
not a 60s poll), and built-in staleness handling (`expire_after` +
availability topic) instead of hand-rolled Jinja timestamp math. Bonus:
`architecture.md` already shows "Home Assistant -> MQTT / REST Events ->
Ardua AI" as this project's planned Phase 5 direction -- standing up
Mosquitto now is the first real piece of that infrastructure, not a
one-off.

## Real findings from building this (not assumptions)

- **The Supervisor CLI (`ha`) has no `options`/`config` subcommand for
  add-ons in this version.** `ha apps --help` lists install/start/stop/
  restart/logs/etc. but nothing for setting an add-on's configuration --
  the expected path is the web UI. Set the Mosquitto add-on's `logins` list
  by calling the Supervisor's own REST API directly instead: `docker exec
  hassio_cli` has `SUPERVISOR_TOKEN` in its environment (the same token the
  `ha` binary itself uses internally, since `/usr/bin/ha` is just a wrapper
  that execs into the `hassio_cli` container), so `curl -X POST -H
  "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/core_mosquitto/options`
  works. **The options endpoint is a full replace, not a merge** -- POSTing
  just `{"logins": [...]}` fails with "Missing option 'customize' in root"
  even though only `logins` changed; the complete options object (all of
  `certfile`/`keyfile`/`require_certificate`/`log_dest`/`log_type`/
  `customize`/`logins`) must be sent every time.
- **Adding any `logins` entry disables anonymous MQTT access broker-wide.**
  This broke HA's own "Add Integration -> MQTT" flow: the connection form
  defaults to blank username/password, and once `govee-collector` was
  added as a login, an anonymous connection got rejected outright
  (`Not authorized`), which surfaced in the UI only as a generic "Please
  enter the connection information of your MQTT broker" re-prompt with no
  specific error. Fixed by adding a second, dedicated `homeassistant`
  login for HA's own connection to its co-located broker -- confirmed the
  failure mode directly (a plain anonymous `paho-mqtt` connect attempt
  returned `Not authorized`) before assuming that was the cause, and
  confirmed the fix by testing the new login authenticates successfully
  before handing the credentials back for the form.
- **MQTT discovery's `object_id` field is not honored when a `device`
  block + `has_entity_name: true` are both used** -- confirmed live, not
  assumed from docs. The collector's discovery payload sets
  `object_id: "wineador_temperature"` on every entity specifically to get
  short, predictable entity IDs, but the entities HA actually created were
  `sensor.wineador_th01_temperature`, `sensor.desk_th03_signal_strength`,
  etc. -- generated from the combined device+entity **display name**
  ("Wineador (TH01)" + "Temperature", slugified), ignoring `object_id`
  entirely. `cigar_dashboard/govee_history.py` was written against the
  wrong assumed IDs at first and fixed once this was caught by directly
  querying the recorder DB for the real entity IDs rather than trusting
  the discovery payload. `govee_collector/discovery.py` still sets
  `object_id` (harmless, spec-correct) but its docstring now documents
  that it isn't actually load-bearing for this entity shape.
- **The Mosquitto add-on's (v7.1.0) options schema has no structured
  per-topic ACL field** -- only `logins` (username/password pairs) and a
  `customize` option pointing at a folder for raw config-file overrides
  (the mechanism with the known reliability issue flagged before this was
  built). Per explicit instruction, ACL enforcement was not pursued via
  that fragile path. Confirmed directly instead: the dedicated
  `govee-collector` login currently has **full, unscoped broker access**
  (tested live -- it can publish/subscribe outside `govee/#` without being
  rejected), not anonymous, but not topic-restricted either. This is the
  accepted, documented state, not an oversight.
- **BlueZ D-Bus permission for a non-root systemd service was a
  non-issue.** The collector runs as `User=jramsey` (not root, no
  `bluetooth` group added) and connected/scanned successfully on first
  boot with zero permission errors -- the one genuinely-unverified risk
  flagged before deployment turned out not to be a problem at all on this
  Debian 13 (trixie) install.
- **LWT-driven availability is fast and reliable, tested live, not just
  configured.** Stopping the `govee-collector` systemd service (graceful
  `SIGTERM`, which the code's `finally` block turns into an explicit
  `offline` publish before disconnecting) flipped all 12 entities to
  `unavailable` within about a minute -- well before the 5-minute
  `expire_after` would have mattered on its own. Restarting the service
  brought all entities back with real values within seconds, confirmed
  directly via the recorder DB, not assumed from the systemd unit's
  `Restart=always`.
- **HA's own native Bluetooth integration independently discovers these
  same Govee sensors too**, since domus apparently has its own onboard/USB
  Bluetooth adapter within range -- a "Govee Bluetooth" discovery card
  appeared in Settings -> Devices & Services alongside the MQTT setup flow.
  **Deliberately not accepted** -- adding it would create a second,
  differently-shaped, redundant set of entities with no continuity with
  what this package's dashboard reads. Worth remembering this card may
  keep reappearing; it should stay ignored/dismissed, not added.
- **BLE advertisement delivery can silently stop while the process keeps
  running, with no crash and no error** -- found live (2026-08-08), not
  theoretical: the collector went ~8 hours without a real update, still
  "active" the whole time and still MQTT-connected (LWT stayed "online"),
  just no more advertisements arriving. Root cause not directly provable
  (mrteeny's journald had a gap across the actual failure window), but
  strong circumstantial evidence points to a second, independent BLE
  scanner (a separate script, `table.py`, left running overnight reading
  the same 3 devices) contending for the one adapter -- when the collector
  was later restarted to recover, it failed outright with
  `org.bluez.Error.InProgress` ("Operation already in progress"), the
  textbook BlueZ symptom of exactly that kind of contention. Recovery
  needed a real adapter-level reset (`hciconfig hci0 down`/`up` +
  `systemctl restart bluetooth`) -- restarting just `bluetoothd` alone was
  not sufficient, and neither was restarting the collector process itself
  (it kept hitting the same `InProgress` error on every retry). **Fixed
  with a self-healing watchdog** (`is_stale()`/`should_attempt_restart()`
  in `collector.py`, both pure and unit-tested): if no real Govee
  advertisement lands within 3 minutes (deliberately far inside the
  5-minute HA `expire_after`, so this self-heals before HA would ever mark
  anything unavailable), the collector stops and restarts its own
  `BleakScanner` session, with a 60s cooldown between attempts so a
  genuinely stuck adapter doesn't get hammered. This does **not** cover
  the harder BlueZ-adapter-lockup case (the `InProgress` failure mode) --
  that needs a lower-level reset the collector can't perform without
  additional privileges it deliberately doesn't have (`User=jramsey`, no
  `bluetooth` group, no `CAP_NET_ADMIN`); see "Known risks" below.
  **Practical takeaway: don't run any other independent BLE-scanning
  script against this adapter while the collector is live** -- confirmed
  the two are not safe to run concurrently.

## File layout

- `govee_collector/` (deploys to **mrteeny**, not domus -- the first
  package in this repo targeting a third host):
  - `decode.py` -- `SENSORS`/`GOVEE_MANUFACTURER_ID`/`DEVICE_LABELS` +
    `decode_h5075()`, ported from the working prototype (`~jramsey/scan.py`
    on mrteeny) with no logic changes.
  - `discovery.py` -- pure functions building the 12 HA MQTT-discovery
    `(topic, payload)` pairs (3 devices x temperature/humidity/battery/
    signal strength), fully unit-tested without a broker.
  - `collector.py` -- `BleakScanner` glue + `paho-mqtt` publish. Decouples
    BLE advertisement rate (every few seconds per device) from MQTT
    publish rate via a 15s periodic flush of in-memory state, so 3 chatty
    devices don't multiply broker traffic. Sets an LWT (`govee/collector/
    status`) at connect time and republishes all discovery config
    (retained, idempotent) on every connect/reconnect.
  - `systemd/govee-collector.service` -- checked-in template, installed by
    hand on mrteeny; `Restart=always`, MQTT password supplied via
    `/etc/govee-collector.env` (root:600, not repo-tracked -- systemd
    itself reads it as root before dropping to `User=jramsey`, so the
    unprivileged service process never needs filesystem access to the
    secret file directly).
  - `deploy.sh` -- rsync to mrteeny + printed (not auto-run) manual steps:
    apt packages, the env file, systemd install/enable.
- `cigar_dashboard/` (deploys to **domus**, mirrors `home_dashboard`'s
  layout exactly):
  - `govee_history.py` -- current + 7-day-history readers, built directly
    on `energy_report.ha_recorder`'s existing `get_latest_state`/
    `get_numeric_sensor_samples` -- no new SQL.
  - `render.py` -- HTML/CSS/JS shell + `data.json` builder. Two
    multi-series charts (`drawMultiSeries`, forked from `home_dashboard`'s
    single-series `drawSparkline`) -- humidity (larger, first) and
    temperature (smaller, second), each overlaying all 3 devices on one
    shared axis with a legend. Three current-reading cards, humidity in
    the largest font per the requested visual emphasis. No PWA manifest,
    Wake Lock handling, or kiosk chrome -- unlike `home_dashboard`, this
    isn't an always-on kiosk display, so none of that was needed.
  - `generate_dashboard.py` -- CLI entry point, cron-invoked every 2
    minutes.
  - `deploy.sh` -- mirrors `home_dashboard/deploy.sh`'s pattern exactly.

## Setup

1. Mosquitto broker: `ha addons install core_mosquitto && ha addons start
   core_mosquitto` (installed as an official HA add-on, not a standalone
   docker container -- zero extra infra, auto-discovered by HA's own MQTT
   integration).
2. Two dedicated logins added via the Supervisor API (see "Real findings"
   above for why the CLI/UI options path doesn't work): `govee-collector`
   (the BLE collector's own credential) and `homeassistant` (HA's
   connection to its co-located broker).
3. `govee_collector/deploy.sh`, then by hand on mrteeny: `apt-get install
   python3-bleak python3-paho-mqtt`, create `/etc/govee-collector.env`,
   install + enable the systemd unit.
4. HA's MQTT integration: Settings -> Devices & Services -> Add Integration
   -> MQTT, broker `core-mosquitto`, port `1883`, username/password from
   step 2's `homeassistant` login. This is a one-time interactive step --
   consistent with this project's standing avoidance of long-lived HA API
   tokens (same tradeoff already made for Nest/Google OAuth and Matter
   commissioning), there's no way to complete this config-entry flow
   programmatically without one.
5. `cigar_dashboard/deploy.sh`, then the printed manual steps: run once by
   hand to sanity-check `data.json` before automating, cron entry, `/cigars/`
   nginx block, `ha-proxy` container recreate (confirm current binds via
   `docker inspect` first, same discipline as every other dashboard here).

## Collector health indicator

Added after the ~8h silent stall (see "Real findings") made clear that
"the process is still running" is not the same as "data is actually
flowing," and that distinction needs to be visible somewhere a human will
actually see it, not just buried in `journalctl`.

The collector publishes a third topic, `govee/collector/health` (JSON,
retained, every flush cycle -- `{"status": "ok"|"stale"|"stuck",
"seconds_since_last_advertisement": N, "consecutive_restart_failures": N}`),
which becomes 3 more HA entities via discovery, grouped under their own
"Govee Collector" device (separate from the 3 physical sensors):

- `binary_sensor.govee_collector_problem` (`device_class: problem`) -- on
  for either `stale` or `stuck`, off for `ok`. The one entity worth an HA
  automation/notification on, if that's ever wanted later.
- `sensor.govee_collector_status` -- the raw status string, for diagnosis.
- `sensor.govee_collector_seconds_since_last_reading` (`device_class:
  duration`) -- how long it's actually been since real data arrived.

`status` escalates from `ok` -> `stale` (the watchdog is actively retrying,
see the earlier "Real findings" entry) -> `stuck` (>= 3 consecutive failed
restart attempts -- `STUCK_AFTER_CONSECUTIVE_FAILURES` in `collector.py`;
this is the case that needs a human, since the watchdog alone can't fix a
genuinely locked BlueZ adapter).

**The dashboard itself surfaces this**, not just HA: `cigar_dashboard`
reads the same 3 entities (`get_collector_health()` in `govee_history.py`)
and shows a red banner at the top of `/cigars/` whenever `is_problem` is
true, with the exact manual-reset commands
(`RESET_INSTRUCTIONS` in `render.py`) printed directly in the banner --
copy-pasteable on the spot, no need to go find this doc first. A gap state
(entities missing/unavailable -- e.g. the collector's MQTT connection is
down entirely, or HA itself just restarted) is deliberately treated as a
problem too, not silently hidden -- unlike a single sensor reading (where
"--" is the right, low-stakes answer for a gap), this indicator's entire
job is catching anomalies, so "we can't tell" should read as "go check,"
not as "everything's fine."

## Dashboard-side data freshness check

Added 2026-09-09, directly because of that day's incident: every warning
layer built before it keyed off the collector's own health self-report, so
when that one signal lied, all of them went quiet together. This is the
independent second opinion that was missing.

`compute_data_freshness()` in `cigar_dashboard/govee_history.py` asks a
question the collector can't answer wrongly -- *did rows actually land in
the recorder?* -- using sample timestamps the dashboard already fetched for
its charts, so it costs no extra query. Two thresholds, because there are
two distinct failures:

- **All three devices quiet for > 15 minutes** -> a collector/adapter
  problem. Three sensors falling silent *together* is not coincidence, so
  this flags fast, and the banner says plainly that the collector's own
  claim is not to be trusted (quoting it, so a reader who then checks HA
  and sees `ok` isn't left thinking the dashboard is confused). The
  BLE-adapter reset commands are shown.
- **One device quiet for > 60 minutes** while the others report -> that
  sensor's own problem: a dead battery, or moved out of BLE range. Names
  the device, and deliberately does *not* show the adapter-reset commands,
  since resetting hci0 is the wrong advice for a dead coin cell.

**Both thresholds were measured, not guessed.** Against 154 hours of real
healthy history from these three sensors (humidity and temperature merged
per device -- a new row on either metric proves the device is alive, and
humidity alone can legitimately hold one value for a long stretch in a
stable humidor): median gap 15s, worst healthy per-device gap 49 minutes
(TH01), and TH03 never exceeded 17 minutes across the whole week.
Simulating both rules minute-by-minute over that window produced **zero**
false alarms. Replaying the actual captured incident data through the
finished check produces the intended banner -- "No new readings from any
sensor in 12h 49m, though the collector reports \"ok\"" -- which means it
would have fired at about 04:20 rather than being noticed by a human at
17:00.

One incidental cleanup came with it: the banner's message strings used to
be written twice, once in Python for first paint and again in the page's
client-side JS for the 60-second refetch. The message is now built once in
`render.py`'s `_banner()`, shipped in `data.json`, and merely displayed by
the JS -- one source of truth, and a test (`test_page_js_reads_the_prebuilt
_banner_rather_than_rebuilding_it`) fails if that ever regresses.

## Preemptive nightly BLE reset

`hci0` wedged into a silent `org.bluez.Error.InProgress` state twice
(2026-08-10 and 2026-08-14), both times with no contending process (no
`table.py`/`scan.py` running, `bluetoothd` otherwise healthy) -- BlueZ
itself appears to periodically get stuck on its own, independent of
anything this project controls. The collector health indicator above
correctly caught both, but a human still had to SSH in and run the fix
each time.

`govee_collector/ble_nightly_reset.sh` runs that same fix (`hciconfig hci0
down`/`up`, `bluetooth` service restart, `govee-collector` restart)
proactively every night at 4am America/Denver via cron on mrteeny, rather
than waiting for the watchdog to detect and exhaust retries. This causes a
brief (~10-20s) gap in cigar-storage monitoring at that hour -- an
acceptable tradeoff against needing manual intervention every few days.
Uses passwordless `sudo` already scoped to `hciconfig`/`systemctl` on
mrteeny; the collector process itself was still deliberately not given
`CAP_NET_ADMIN`/root (see "Known risks" below).

Deployed via `govee_collector/deploy.sh`'s step 4 (cron entry is a
one-time manual step, same reasoning as the systemd unit install --
touches host-level standing state, not silently applied by the script).
Smoke-tested live by running the script directly: adapter reset cleanly,
`govee-collector` and `bluetooth` both came back `active`, fresh
advertisements confirmed flowing within seconds.

## On-detection BLE auto-reset

The nightly reset only covers overnight -- `hci0` wedged a third time on
2026-08-21, mid-afternoon, and the cigar dashboard's red banner sat
visible until a human noticed and SSH'd in to run the same manual fix.
`govee_collector/ble_auto_reset.py` closes that gap: cron'd every 2
minutes on mrteeny, it parses this host's own `journalctl -u
govee-collector` for `collector.py`'s own `"Collector health: stuck"` log
line (reusing the collector's already-tuned stale/stuck thresholds --
`STALE_RESTART_THRESHOLD_SECONDS`, `STUCK_AFTER_CONSECUTIVE_FAILURES` --
rather than re-deriving them) and, if stuck, runs
`ble_nightly_reset.sh` -- the identical, already-proven reset sequence,
called directly rather than duplicated.

Deliberately entirely local to mrteeny -- no dependency on domus, Home
Assistant, or the MQTT broker being reachable, since this project
separately hit a ~10-hour cross-host connectivity outage that week (see
docs/automation-health.md); a detector that depended on the same kind of
remote reachability to notice a *local* hardware wedge would be a bad bet.

If a reset doesn't actually clear the stuck state, retrying
`hciconfig`/`systemctl restart bluetooth` every 2 minutes forever isn't
right -- excessive bluetoothd restarts, and persistent failure means
something worse than the known transient wedge. A small state file
(`govee_collector/auto_reset_state.json`, gitignored -- it's runtime
state, not config) tracks `consecutive_failed_resets` and backs off the
retry interval the same tiered way `automation_health`'s weather-upload
automations do: immediate, then 5min, then 15min, then capped at hourly.
The count clears back to 0 the moment health is next observed as anything
other than "stuck" -- proof a reset (or a self-recovery) actually worked.

Verified against the real captured log lines from the 2026-08-21 incident
(15:38-15:40, the exact window a human manually reset it in) --
`current_status()`/`should_reset()` correctly identify that window as
needing an immediate reset attempt.

## 2026-08-22: crash-loop went undetected for over an hour -- two real bugs

The dashboard's banner reappeared the next day with a different message
("Collector health unknown"), and the auto-reset above never fired.
Investigation found a genuinely different failure mode, and two real bugs
in the code written to handle the first one.

**A different failure mode.** `dmesg` showed `hci0` had wedged at the
*kernel* level (`command 0x200c tx timeout`, even a basic HCI Reset --
`Opcode 0x0c03` -- failing), below where `hciconfig`/`bluetoothd` operate.
Confirmed live: manually re-running `ble_nightly_reset.sh`'s own
`hciconfig hci0 up` failed with the same `Connection timed out (110)`.
Only a full reboot cleared it (the user rebooted directly; `docker ps`
showed nothing running and no NFS mounts active, so it was low-risk).

**Bug 1**: the reset script's `hciconfig` call failing silently (via
`set -uo pipefail`, not `-e`, so the script continues past a failed step)
meant `govee-collector` restarted into an immediate crash loop --
`await scanner.start()` throws before the code that logs `"Collector
health: X"` is ever reached, so the crash-looping process produced *zero*
matching log lines. The original `ble_auto_reset.py` treated "no health
line in the window" as healthy and cleared the failure count -- so it
never retried and never escalated, for over an hour, completely silently.

**Bug 2, found while fixing Bug 1**: `collector.py` only logs `"Collector
health: X"` when status is NOT `"ok"` (`if health_status !=
HEALTH_STATUS_OK:`) -- a genuinely healthy collector produces *zero*
matching lines too. So "no health line at all" is ambiguous by
construction between "everything's fine" and "crashed before it could
report anything" -- the exact two cases that need opposite responses. The
original code couldn't tell them apart (that's what made Bug 1 possible
in the first place: the fix for Bug 1 isn't "treat None as stuck",
because that would also start incorrectly resetting a genuinely healthy
collector every cycle).

**Fix**: `service_is_active()` adds a second, independent signal --
`systemctl is-active govee-collector` -- which distinguishes a truly
running process from one stuck in systemd's restart loop (`activating`,
exactly this incident's real state) or dead (`failed`). Disambiguation:
no health line + service genuinely active = healthy (clears backoff); no
health line + service not active = needs a reset, same urgency as
`"stuck"`. `"stale"` is left alone either way -- `collector.py`'s own
watchdog is still within its own retry budget for that one.

Considered and rejected: making `collector.py` log an explicit `"ok"`
line every `FLUSH_INTERVAL_SECONDS` (15s) to close the ambiguity at the
source instead. Would work, but turns a "log on problems only" daemon
into one logging ~5,760 lines/day of pure noise for the routine case --
`service_is_active()` gets the same disambiguating signal from systemd
directly, for free, without touching the well-tested core daemon's
logging cadence.

Deployed and confirmed live: ran the fixed script by hand against the
now-healthy (post-reboot) collector -- correctly identified no health
line + service active as healthy, made no unnecessary state-file writes.

## Reboot escalation

The 2026-08-22 incident's *actual* root cause -- a kernel-level HCI
lockup -- can't be fixed by `hciconfig`/`bluetoothd` at all (confirmed
live: a manual retry of the exact same commands failed identically).
Only a full reboot cleared it. `ble_auto_reset.py` now escalates to one
automatically: after `REBOOT_AFTER_CONSECUTIVE_FAILURES` (3) failed
`hciconfig`-based resets -- still gated by the existing tiered backoff,
so this is the *fourth* remediation attempt overall, roughly 80 minutes
into an incident -- the next action is `sudo reboot`, run locally (this
script already executes on mrteeny via its own cron with the same
passwordless sudo `ble_nightly_reset.sh` uses; no SSH involved, unlike
the separate permission granted for this session's own interactive use).

**Give-up condition, the user's explicit call**: if the collector is
still unhealthy `REBOOT_GRACE_PERIOD_MINUTES` (10) after that reboot, the
script gives up entirely -- sets a sticky `gave_up` flag, prints an error,
exits 1, and takes no further remediation action on any subsequent run
while still unhealthy. Reasoning: a reboot that doesn't fix it means
something is actually broken (hardware fault, not the known transient
lockup class), and rebooting repeatedly forever wouldn't help -- it needs
a human. `gave_up` (and `rebooted_at`, and the failure counter) all clear
back to fresh state the moment health is next genuinely observed, so a
future, unrelated incident starts clean rather than inheriting a stale
give-up from a previous one.

State schema (`govee_collector/auto_reset_state.json`, gitignored --
runtime state, not config): `last_reset_at`, `consecutive_failed_resets`,
`rebooted_at`, `gave_up`. `load_state()` fills in `rebooted_at`/`gave_up`
with their defaults when reading a state file written by the pre-escalation
version of this script, so no migration step was needed.

Not live-tested end to end (deliberately -- that would mean forcing a
real, extended BLE outage and a real reboot for no operational benefit,
given the mechanism itself -- `sudo reboot` with mrteeny's existing
passwordless sudo -- is the same one already used manually and by the
nightly script). Instead: 8 new unit tests cover every state transition
precisely (escalates at the right failure count, waits out the full grace
period, gives up exactly at the boundary, stays given-up on subsequent
runs without re-checking timing, recovery clears all incident state, not
just the failure counter) -- 41 tests total for this module, 371 project-
wide. Deployed and confirmed live against the actual healthy system: ran
by hand, correctly took no action and did not reboot.

## 2026-09-09: 13 hours blind while health reported "ok"

Found by a human noticing the dashboard's three current readings were
blank while the graphs still looked fine -- exactly the failure mode every
layer above was built to make impossible. Worth reading as a unit with the
2026-08-22 entry: the recovery machinery was all present and correct, and
none of it fired, because the signal it keys off was lying.

**What happened.** hci0 had been logging `Frame reassembly failed (-84)`
intermittently since ~02:45. The nightly reset ran at 04:00 into an
already-degrading adapter and pushed it into the same kernel-level HCI
lockup as 2026-08-22 (dmesg: `command 0x0c14 tx timeout`, then
`Opcode 0x0c03 failed: -110` -- a plain HCI Reset timing out, and
`hciconfig -a` unable even to read the adapter's local name).
`ble_auto_reset.py` correctly caught the resulting crash-loop and reset at
04:04, after which the collector came up "active" and stayed that way. All
12 device entities went `unavailable` at 04:04:54 -- exactly
`expire_after` (5 min) past the last pre-restart publish -- and stayed
unavailable for 13 hours. The graphs kept looking healthy because they
draw a 7-day window, and 13 missing hours at the right edge don't read as
obviously wrong at a glance.

**Why nothing escalated.** The watchdog's restart path did two things
wrong, both of which only matter when BlueZ lies:

1. It set `last_advertisement_at = time.time()` whenever `scanner.start()`
   returned without raising ("give the fresh session a full window"), and
2. it only incremented `consecutive_restart_failures` when that call
   actually raised.

In this lockup class every BlueZ call succeeds and no advertisement is
ever delivered. So every 180 seconds the watchdog noticed the stall,
"restarted successfully," reset its own staleness clock, and left the
failure count at zero -- meaning `compute_health_status()` returned `ok`
at every single flush. `stale` was transient and `stuck` was
*unreachable*. Downstream, that one lie disabled everything:

- `sensor.govee_collector_seconds_since_last_reading` published ~135, not
  ~47,000, so the number a human would check looked perfect.
- `collector.py` only logs `Collector health: X` when the status is *not*
  `ok`, so it emitted no health lines at all -- which
  `ble_auto_reset.py` reads, correctly per its own documented rules, as
  "None + service active = healthy." It logged "No health line, but the
  service is genuinely active -- clearing all recovery state" every 2
  minutes for 13 hours, and never escalated to the reboot that would have
  fixed it in one step.
- The dashboard's red problem banner never appeared, because
  `is_problem` was honestly reporting what HA had been told.

**The fix.** An advertisement is now the *only* evidence a restart worked.
`after_restart_attempt()` never advances `last_advertisement_at` and
increments the failure count up front, on every attempt; only
`after_advertisement()` (called from the BLE callback on a real decode)
clears it. Both known lockup classes are then covered by one rule: the
noisy one (`start()` raises) and the silent one (`start()` lies). With the
fix, a blind adapter reaches `stuck` within a few minutes, which logs,
which `ble_auto_reset.py` acts on, which escalates to a reboot.

**Testability was the actual root cause.** The bug lived in `run()`'s
loose local variables -- the one part of `collector.py` with no unit tests,
precisely because it was tangled up with asyncio and bleak, while every
pure function around it was well covered. The watchdog bookkeeping is now
a `WatchdogState` value with two pure transitions, following the same
pattern `apply_advertisement()` already used for device state, so the
whole failure mode is simulatable with no hardware. Four new tests cover
it; all four fail against the old logic (verified by reverting the
transition and re-running), and the blind-adapter simulation reproduces
the observed symptom exactly: `ok` forever, `stuck` never reached.

**Recovery on the day** was a reboot, again -- `ble_nightly_reset.sh` run
by hand failed identically to 04:00 (`Can't init device hci0: Connection
timed out (110)`), confirming the lockup class before escalating. All 3
sensors were reporting within ~2 minutes of the reboot.

## Known risks / things to watch

- **The `govee-collector` MQTT login has full, unscoped broker access**,
  not topic-restricted (see "Real findings" -- the add-on's ACL mechanism
  either isn't exposed in a structured way in v7.1.0 or has the known
  reliability issue). Low practical risk (this is a home LAN broker with
  no WAN exposure), but worth revisiting if the "customize" folder ACL
  mechanism ever gets fixed upstream, or if this broker ever hosts
  higher-stakes topics later (e.g. the planned Phase 5 Ardua AI event
  stream).
- **HA's native Bluetooth "Govee Bluetooth" discovery card may keep
  reappearing** in Settings -> Devices & Services, since domus has its own
  BT adapter in range of these sensors. Leave it ignored -- accepting it
  would create a redundant, differently-shaped set of entities.
- **`object_id` in the discovery payload is currently inert** for this
  entity shape (see "Real findings") -- if `govee_collector/discovery.py`
  is ever revised to drop the `device`/`has_entity_name` grouping, entity
  IDs would change behavior and `cigar_dashboard/govee_history.py`'s
  `_entity_id()` would need re-verifying against live data again, not
  just re-derived from the new payload shape.
- **7-day chart with less than 7 days of data** (the real state on day 1)
  is explicitly tested (`test_get_temp_history_less_than_seven_days_of_data_is_not_an_error`)
  and renders correctly -- not just assumed to work.
- **The watchdog can't recover from a genuinely stuck BlueZ adapter**
  (`org.bluez.Error.InProgress`) on its own -- that needed a manual
  `hciconfig hci0 down`/`up` + `bluetooth` service restart, live, on
  2026-08-10, 2026-08-14, and again 2026-08-21 (see "Real findings"), all
  three times with no contending process -- BlueZ itself appears to
  periodically wedge independent of anything this project controls.
  That's a recurring, not one-off, annoyance, so two layers now cover it:
  `govee_collector/ble_nightly_reset.sh` (nightly at 4am, before the
  watchdog would ever need to notice) and `ble_auto_reset.py` (every 2
  minutes, on-detection, for a wedge any other time of day -- see "On-
  detection BLE auto-reset" above; 2026-08-21's wedge happened mid-
  afternoon and sat visible on the dashboard until manually noticed,
  which is exactly the gap that layer closes). Giving the collector
  enough privilege to do this itself (root, or `CAP_NET_ADMIN`) was still
  deliberately not done -- passwordless `sudo` scoped to
  `hciconfig`/`systemctl`, used only by these two dedicated scripts,
  achieves the same outcome without widening the collector process's own
  privileges.
- **A fourth wedge (2026-08-22) was a different, worse failure class**
  that `hciconfig`/`bluetoothd` alone can't fix -- a kernel-level HCI
  lockup (see "2026-08-22" above), confirmed live (a manual retry of the
  exact same reset commands failed identically). `ble_auto_reset.py` now
  handles this end to end: detects it (Bug 1/2 fixes above), escalates to
  a full reboot after repeated `hciconfig`-based resets fail, and gives up
  with a clear error if the reboot itself doesn't fix it within 10 minutes
  -- see "Reboot escalation" above. The user separately granted this
  session standing permission to reboot mrteeny.ardua.lan directly for
  interactive diagnosis; that's unrelated to (and not required by) the
  automated script, which already has its own local passwordless sudo.
- **The reboot escalation is still not live-tested end to end.** A real
  kernel-level lockup did recur naturally on 2026-09-09 and did *not*
  exercise it -- not because the escalation logic is wrong, but because
  the collector reported `ok` throughout, so nothing ever asked it to run
  (see "2026-09-09" above). That specific blocker is fixed; the escalate-
  then-give-up path itself remains unexercised in production, and the next
  lockup of this class is what will finally test it.
- **`ble_auto_reset.py` still has no independent signal for "the collector
  is running but blind."** It infers health from `collector.py`'s log
  lines plus `systemctl is-active`, and "no health line + active" means
  healthy -- which was the correct reading of an incorrect signal on
  2026-09-09. Fixing the signal at the source restores that inference, but
  the coupling remains: any future bug that stops `collector.py` from
  logging a bad status is again invisible to the *auto-reset* layer.
  The dashboard half of this gap is closed -- its freshness check reads
  recorder timestamps and owes the collector nothing (see "Dashboard-side
  data freshness check") -- but that only makes an outage *visible*, it
  doesn't make recovery *automatic*. Giving `ble_auto_reset.py` the same
  independence (reading the retained `govee/collector/health` topic, or
  the recorder's entity timestamps over SSH) is the remaining piece, and
  is deliberately not built yet: mrteeny reaching across to domus for its
  own health verdict reintroduces exactly the cross-host dependency that
  script was written to avoid.

## Status

- [x] `govee_collector/` (decode, discovery, collector, systemd unit,
      deploy.sh) -- 52 tests passing (93 for the package as a whole,
      including `ble_auto_reset.py`'s 41)
- [x] Mosquitto broker installed, two dedicated logins configured
- [x] Deployed to mrteeny, verified live via `mosquitto_sub`: all 3
      devices publishing correct discovery config + state
- [x] HA MQTT integration configured (one-time manual step)
- [x] All 12 entities confirmed live with correct `device_class`/
      `unit_of_measurement`, real values landing in the recorder DB
- [x] LWT + `expire_after` staleness tested live (stop/restart the
      collector, watched entities flip unavailable and recover)
- [x] Self-healing watchdog for silent BLE scan stalls (found the real
      failure mode live, ~8h of silent staleness, fixed and redeployed --
      see "Real findings")
- [x] `cigar_dashboard/` (govee_history, render, generate_dashboard,
      deploy.sh) -- 45 tests passing
- [x] Deployed to domus and verified end-to-end: cron entry live, `/cigars/`
      nginx block added, `ha-proxy` recreated with the new bind mount
      (confirmed `/dashboard/` and `/energy-report/` unaffected), real
      multi-device data rendering in `data.json`/`index.html`
- [x] `https://domus.ardua.com/cigars/data.json` is the same file the
      page's own client-side JS polls -- served directly by nginx alongside
      `index.html`, no separate API needed. Confirmed live (HTTP 200,
      `content-type: application/json`, real current readings + full
      per-device `humidity_history`/`temp_history` arrays) for anyone who
      wants to consume the raw timeseries directly rather than the
      rendered page.
- [x] Collector health indicator (`binary_sensor.govee_collector_problem`
      + 2 diagnostic sensors, dashboard banner with the exact manual-reset
      commands baked in) -- see "Collector health indicator" above,
      confirmed live: correctly hidden while healthy
      (`{"is_problem": false, "status": "ok"}` flowing through to the real
      `data.json`).
- [x] Shared cross-page nav + light/dark/auto theming (`site_shared`
      package) -- top nav bar with a toggle, chart gridline/label colors
      redraw on theme change from cached data. Full writeup in
      `docs/site-shared.md`. Explicitly did NOT gain a PWA manifest/icon
      link -- only `home_dashboard` is meant to be independently
      installable.
- [x] Preemptive nightly BLE adapter reset (`ble_nightly_reset.sh`,
      cron'd 4am America/Denver on mrteeny) -- added after the BlueZ
      wedge recurred a second time (2026-08-10, 2026-08-14). See
      "Preemptive nightly BLE reset" above.
- [x] On-detection BLE auto-reset (`ble_auto_reset.py`, 33 tests passing,
      cron'd every 2 minutes on mrteeny) -- added after the wedge recurred
      a third time (2026-08-21), mid-afternoon, outside the nightly
      window. Entirely local to mrteeny (parses `journalctl`, no
      dependency on domus/HA/MQTT reachability), tiered backoff if a
      reset doesn't actually clear it. See "On-detection BLE auto-reset"
      above.
- [x] Fixed two real bugs after a fourth wedge (2026-08-22) went
      undetected for over an hour: a crash-looping collector produced no
      health log lines at all (treated as healthy, not as "possible
      crash"), and that ambiguity existed because `collector.py` never
      logs an explicit "ok" line either. `service_is_active()` adds
      `systemctl is-active` as a second, independent signal to
      disambiguate. See "2026-08-22: crash-loop went undetected" above.
- [x] BLE watchdog no longer trusts a non-raising `scanner.start()` as
      proof of recovery (2026-09-09 -- 13 hours blind while publishing
      `ok`); watchdog bookkeeping extracted to a pure `WatchdogState` so
      the failure is simulatable, 4 regression tests that all fail against
      the old logic. See "2026-09-09" above.
- [x] Dashboard-side data freshness check, independent of the collector's
      self-report -- thresholds measured against 154 hours of real history
      (zero false alarms), verified by replaying the captured incident
      data. See "Dashboard-side data freshness check" above.
- [x] Reboot escalation (41 tests passing for `ble_auto_reset.py`, 371
      project-wide) -- after repeated `hciconfig`-based resets fail,
      escalates to `sudo reboot` (local, same passwordless sudo the
      nightly script already uses); gives up with a clear error if still
      broken 10 minutes after that reboot, rather than rebooting
      repeatedly forever. See "Reboot escalation" above.
- [x] Swipe-to-navigate between the three pages (`nav.render_swipe_nav_script`
      in `site_shared`). Full writeup in `docs/site-shared.md`. Confirmed
      live on a real iPad, both directions.
- [x] Manual light/dark/auto toggle removed entirely, from every page --
      the site always follows the OS now. Nav links are also now hidden
      on any touch-capable device (swipe replaces them there) -- confirmed
      via a real iPad simulator that `.site-nav` is fully hidden on this
      page. Full writeup in `docs/site-shared.md`.
- [x] Visually reviewed in an actual browser at
      `https://domus.ardua.com/cigars/` -- booted an iPad Air simulator
      and confirmed by screenshot (nav hidden, swipe working, page
      rendering correctly). The card layout/chart rendering itself was
      last eyeballed this way; the toggle's own visual states are moot
      now that it doesn't exist.
- [ ] The health banner's "problem" visual state hasn't been observed live
      (only unit-tested + confirmed via the underlying data pipeline) --
      the original stuck-adapter incident that motivated this happened
      before the indicator existed, so there's no real "stuck" case to
      observe it against yet
- [ ] A genuine 7-day history hasn't accumulated yet -- charts are correct
      given the data that exists, but haven't been seen with a full week
      of real trend lines
- [x] Nav now links to a 4th page, `control_panel` (`/control/`) --
      no changes needed here beyond `site_shared.nav.PAGES` gaining an
      entry. See `docs/control-panel.md`.
