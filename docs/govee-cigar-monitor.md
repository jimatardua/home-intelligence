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
  `hciconfig hci0 down`/`up` + `bluetooth` service restart once, live (see
  "Real findings"). If this recurs and `Restart=always` ends up
  crash-looping indefinitely instead of self-healing, that's the fix:
  `sudo hciconfig hci0 down && sudo hciconfig hci0 up && sudo systemctl
  restart bluetooth`, then `sudo systemctl restart govee-collector`.
  Giving the collector enough privilege to do this itself (root, or
  `CAP_NET_ADMIN`) was deliberately not done -- a real tradeoff against
  this project's least-privilege habits, worth revisiting only if manual
  recovery becomes a recurring, not one-off, annoyance.

## Status

- [x] `govee_collector/` (decode, discovery, collector, systemd unit,
      deploy.sh) -- 47 tests passing
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
      deploy.sh) -- 23 tests passing
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
- [ ] Visually reviewed in an actual browser at
      `https://domus.ardua.com/cigars/` (built and verified via `curl`
      and direct file inspection so far, not yet eyeballed live)
- [ ] The health banner's "problem" visual state hasn't been observed live
      (only unit-tested + confirmed via the underlying data pipeline) --
      the original stuck-adapter incident that motivated this happened
      before the indicator existed, so there's no real "stuck" case to
      observe it against yet
- [ ] A genuine 7-day history hasn't accumulated yet -- charts are correct
      given the data that exists, but haven't been seen with a full week
      of real trend lines
