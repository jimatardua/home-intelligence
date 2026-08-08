# Changelog

All notable changes to this project are documented here. Version is tracked
in the root `VERSION` file (this project has no single package manifest, so
`VERSION` is the canonical source of truth; the RMP HA integration's own
`manifest.json` version is independent, scoped to Home Assistant's own
per-integration update tracking).

## [1.0.29] - 2026-08-08

- Add a visible collector-health indicator for the Govee cigar-storage
  monitor: 3 new diagnostic HA entities
  (`binary_sensor.govee_collector_problem` + status/duration sensors,
  grouped under their own "Govee Collector" device via a new
  `govee/collector/health` MQTT topic) distinguish "still retrying
  automatically" from "stuck, needs a human" -- the 1.0.28 watchdog fixed
  the common silent-stall case but gave no visibility into the harder
  adapter-lockup case. The `cigar_dashboard` page now shows a red banner
  at `/cigars/` whenever there's a problem, with the exact manual
  `hciconfig`/`bluetooth` reset commands printed directly in the banner --
  no doc-digging needed in the moment. A gap/unavailable state is treated
  as a problem too, not silently hidden. 16 new tests (47 in
  `govee_collector`, 23 in `cigar_dashboard`, 70 total).

## [1.0.28] - 2026-08-08

- Fix a real reliability gap in the Govee cigar-storage collector (1.0.27),
  found live the morning after deployment: BLE advertisement delivery can
  silently stop while the systemd service keeps running and stays
  MQTT-connected -- no crash, no error, just no more data, undetected for
  ~8 hours. Root cause not directly provable (a journald gap on mrteeny
  covered the actual failure window), but strong circumstantial evidence
  points to a second independent BLE-scanning script left running
  overnight contending for the one adapter -- recovering the collector
  required a real `hciconfig`/`bluetooth` adapter reset, and the restart
  attempt itself failed first with the textbook BlueZ contention error
  (`org.bluez.Error.InProgress`). Added a self-healing watchdog
  (`is_stale()`/`should_attempt_restart()`, both pure and unit-tested):
  if no real advertisement lands within 3 minutes, the collector restarts
  its own BLE scan session automatically, well inside the 5-minute HA
  `expire_after` window. 7 new tests (34 total in `govee_collector`).

## [1.0.27] - 2026-08-07

- Add cigar-storage environment monitoring: 3 Govee H5075 BLE
  thermo-hygrometers (wineador/drybox/desk), scanned by a new Raspberry Pi
  (`mrteeny`) running the new `govee_collector` package as a systemd
  service, publishing to a newly-installed Mosquitto MQTT broker (HA
  add-on) via HA's native MQTT Discovery -- 12 auto-created sensor
  entities (temp/humidity/battery/signal strength x 3 devices), with
  LWT + `expire_after` staleness handling verified live (stop/restart the
  collector, watched entities flip unavailable and recover). New
  `cigar_dashboard` package (mirrors `home_dashboard`'s architecture) at
  `/cigars/`: current readings plus 7-day humidity/temperature history via
  two multi-series charts. First package in this repo to deploy to a host
  other than domus. Full architecture, real findings (Supervisor API
  quirks, an MQTT-anonymous-access gotcha, an MQTT-discovery `object_id`
  gotcha), and setup steps in `docs/govee-cigar-monitor.md`.

## [1.0.26] - 2026-07-29

- Replace the Tesla WiFi-arrival `ping` sensors with ARP-based ones: found
  live that Teslas never answer ICMP echo at all, even fully awake and
  actively online (confirmed via pfSense's own ARP table and `pf` state
  table showing a live, connected car while `ping` got 100% loss from both
  the gateway and domus) -- so the `tesla_carport_arrival_refresh`
  automation had silently never fired since being added in 1.0.25, despite
  looking correctly configured. New `command_line` binary sensors
  (`binary_sensor.carport_jim_s_tesla_arp` / `..._irina_s_tesla_arp`, 60s
  poll) read presence from pfSense's live ARP table instead, over a
  dedicated SSH account (`ha-arp-monitor`) whose key is restricted to a
  single forced command (`arp -an`) via `authorized_keys` -- full
  writeup of the setup gotchas (account-lock privilege requirement,
  `authorized_keys` regeneration on GUI save) in hardware.md. Automation
  updated to trigger off the new sensors; old `ping` sensors left in place
  pending manual cleanup via Settings > Devices & Services.

## [1.0.25] - 2026-07-29

- Fix a real reliability gap in the carport temperature feature (1.0.24),
  found live after deployment: HA's Tesla Fleet integration polls the cloud
  API roughly every 10 minutes, and a Tesla can fall fully asleep in that
  same window right after parking -- freezing its last-known (sometimes
  still mid-drive) GPS position until something wakes it again. Confirmed
  directly: a car showed "parked in the carport" while its actual last
  fix was several blocks away. There's no reliable way to react to "just
  parked" after the fact (an accurate GPS position arrives together with a
  parked-status cloud update, or not at all before sleep) -- fixed instead
  with a fully independent, local, near-instant signal: each Tesla's Wi-Fi
  connecting to the home network (a `ping` binary_sensor per car, added via
  HA's UI since `ping` isn't YAML-configurable in current versions, against
  a DHCP-reserved IP found from the real MAC address on each car's own
  Wi-Fi Diagnostics screen -- confirmed by MAC-vendor lookup against
  "Tesla, Inc.", not guessed from ARP-table circumstantial evidence, which
  produced a randomized-MAC false positive first). A new automation
  (`tesla_carport_arrival_refresh`) reloads the Tesla Fleet integration two
  minutes after either sensor connects, forcing a fresh poll while the car
  is still awake.
- Add a 1-hour staleness cutoff to `get_current_gated_temperature()`: a
  reading older than that (the car's been asleep a while, with no way to
  refresh without waking it routinely and draining its battery) is now
  excluded rather than shown as if it were current -- the same "no data
  beats wrong data" convention as everywhere else in `ha_recorder.py`.
  5 new tests (152 total across both packages).
- Home dashboard: move the carport temperature reading next to the main
  outdoor temperature (smaller font, "Carport NN°") instead of stacked
  underneath the condition text, per feedback after seeing it live.

## [1.0.24] - 2026-07-28

- Add a second, independent outdoor-temperature source: the south side /
  carport, derived from whichever Tesla's own `outside_temperature` sensor
  is currently parked there (gated by a new HA "Carport" zone), alongside
  the existing north-side Eve Weather reading -- which runs ~10°F warm from
  patio radiant heat, confirmed empirically (91°F vs. ~80°F on a nearby
  parked Tesla; converged to within a couple degrees when the Eve sensor
  was temporarily moved to the shaded carport). New
  `get_device_tracker_zone_intervals()` and `get_gated_temperature_samples()`/
  `get_current_gated_temperature()` in `energy_report/ha_recorder.py` do the
  zone-membership reconstruction and presence-gated averaging in Python
  (not an HA template sensor), so the logic gets full unit-test coverage;
  reused by both `energy_report`'s TOU chart (a second line on the existing
  "Outdoor temperature vs. usage" chart) and `home_dashboard` (a small
  annotation under the hero temperature, shown only while a car's actually
  parked there). 26 new tests across both packages (147 total), including
  the anchor-at-window-start behavior needed for a car parked since before
  a report's window opens -- a real gap in how the existing
  `get_binary_sensor_intervals()`-style interval reconstruction handles
  state already in effect before a query window, worked around here rather
  than changing that already-relied-upon existing function's behavior.

## [1.0.23] - 2026-07-28

- Correction/completion of the 1.0.22 DNS fix: **disabling Wi-Fi on domus
  was the wrong fix**, and caused a real regression -- it broke
  connectivity to Matter-over-Thread devices (e.g. the Eve Weather sensor)
  entirely, since domus only gets a route to the Thread mesh's IPv6 prefix
  via Wi-Fi's own Router Advertisements (confirmed: with Wi-Fi off,
  `ip -6 route` had no route to the mesh prefix at all and `ping6` failed
  outright with "Network is unreachable"; the Matter server's own
  `ENETUNREACH` errors traced directly back to this, not a stale-cache or
  address-change issue as first suspected). The actual root cause of the
  original DNS flakiness was pfSense's DHCP server handing out an extra,
  occasionally-unreliable DNS server (`192.168.128.3`) alongside the
  primary one -- fixed at the DHCP server itself, which makes running both
  Ethernet and Wi-Fi simultaneously safe again (both interfaces now agree
  on a single resolver). Wi-Fi re-enabled; Matter server restarted once the
  route was actually back, and the Eve Weather sensor confirmed reporting
  live data again. See `hardware.md`'s domus section for the permanent
  operational notes this surfaced.

## [1.0.22] - 2026-07-28

- Fix a real production bug in the LG TV Alexa integration: `media_player.tv`
  (the Universal Media Player wrapper) only explicitly declared `turn_on`,
  relying on implicit passthrough to the underlying `webostv` entity for
  everything else. That passthrough support turned out to depend on the
  child's *live* supported features -- so whenever the TV was fully off
  (and the underlying entity correctly went `unavailable`, its normal
  behavior), `media_player.tv` lost `turn_off` support entirely and "Alexa,
  turn off the TV" failed outright with `ServiceNotSupported` instead of a
  harmless no-op. Fixed by explicitly declaring `turn_off`, `volume_mute`,
  `volume_set`, and `select_source` the same way `turn_on` already was;
  `media_play`/`media_pause`/`media_stop` added proactively for the
  identical reason, closing the same latent gap before it caused the same
  bug for "Alexa, pause the TV."
- The TV's IP address changed twice (no DHCP reservation existed): HA's own
  SSDP-based auto-discovery silently caught the first change, but the
  second needed a manual integration Reconfigure. Fixed for good with a
  DHCP static mapping on pfSense (`192.168.128.111`).
- Add a dedicated "Media" HA dashboard (new sidebar entry, a
  `media-control` card for `media_player.tv`) so the TV can be controlled
  from HA's own UI directly, not just via Alexa.
- Fix chronic, intermittent DNS resolution failures on domus (recurring
  `Cannot connect to host ... [Timeout while contacting DNS servers]`
  errors affecting Tesla Fleet, weather-upload automations, and anything
  else calling out to an external host) -- root cause was domus having both
  Ethernet and Wi-Fi connected simultaneously, each with its own default
  route and, critically, each resolving to a *different* DNS server
  (`systemd-resolved` was aggregating both into `/etc/resolv.conf`,
  producing inconsistent results depending on which got queried). The
  Wi-Fi connection (to "Comanche") was a leftover with nothing depending on
  it -- domus is wired-only per `hardware.md` and Ethernet was already the
  preferred route. Disabled via HA's own Settings -> System -> Network;
  confirmed clean afterward (single default route, single resolver, and a
  25-request burst against every previously-failing host came back fast
  with no timeouts).

## [1.0.21] - 2026-07-27

- Add native Alexa Smart Home support for the family room LG webOS TV
  (55UM7300AUE): "turn on/off the TV," "mute the TV," and per-app launching
  for Netflix/Plex/Prime Video/Apple TV/YouTube TV/antenna now work via Home
  Assistant's local `webostv` integration plus HA's free, self-hosted Alexa
  Smart Home Skill -- not Nabu Casa, not LG's own unusable cloud skill.
  `media_player.tv` (a Universal Media Player) wraps the real `webostv`
  entity to add a working `turn_on` via Wake-on-LAN, which the underlying
  integration doesn't support on its own; seven scripts handle per-app
  launching, exposed to Alexa as scenes. New `alexa_smart_home_bridge/`
  package (AWS Lambda, 9 passing tests) bridges Alexa's directives to HA's
  API; the Lambda, IAM role, and Alexa skill (endpoint + account linking)
  are deployed/configured. Required a public-reachability change in the
  `infrastructure` repo (handoff in `docs/infra-handoff-alexa-lg-tv.md`),
  now complete -- `domus.ardua.com` is publicly reachable through the
  existing local `ha-proxy`, no HA-side proxy-trust config needed.
  Found live, not anticipated going in: Alexa's own built-in recognition of
  major media/content brand names intercepts scene names that exactly match
  one (Netflix, Plex, Prime Video, YouTube TV, and "Live TV") regardless of
  phrasing, before the request ever reaches HA -- fixed by renaming those
  five scenes to a "___ Mode" pattern; "Apple TV" was unaffected and kept
  its original name, with an added "Apple Mode" alias script for naming
  consistency. Verified end-to-end with real Alexa voice commands for every
  target phrase. Full writeup in `docs/alexa-lg-tv.md`.

## [1.0.20] - 2026-07-25

- Harden the Rocky Mountain Power integration against a real production
  incident: a stale login session that couldn't self-heal on its own,
  causing the archive to silently stop updating for 11 days until a
  manual integration reload fixed it (with unchanged credentials,
  confirming the session -- not the password -- was the problem).
  `_invalidate_session()` now actually discards the HTTP session, crypto
  handshake state, and cached agreement, rather than only setting a flag
  that let every subsequent poll keep retrying on the same poisoned
  session. `_login()`'s own failure paths now call it too, so a failed
  login itself (not just a later mid-session failure) guarantees the next
  scheduled poll starts genuinely fresh. Added mocked unit tests
  (`custom_components/rocky_mountain_power/tests/test_api.py`) --
  previously this component had no automated test coverage at all.

## [1.0.19] - 2026-07-23

- Button-up-the-house warning: split the sub-label onto two lines
  ("Outside is warmer" / "Button up the house") instead of one dash-joined
  line -- there's plenty of room in the card for it.

## [1.0.18] - 2026-07-23

- Add a "button up the house" warning: when the A/C is off and it's
  gotten warmer outside than in (free overnight cooling turning into free
  heating), the Indoor card's temperature and sub-label turn red with an
  actionable message. Computed server-side (`_should_button_up_house()`,
  unit-tested) rather than in client JS, with a tunable 1°F margin to
  avoid flicker from sensor noise right at the crossover point.

## [1.0.17] - 2026-07-21

- Move the Eve Weather battery indicator from under the outdoor temp (now
  dead center of the hero row) to a fixed, unobtrusive spot in the page's
  bottom-right corner.

## [1.0.16] - 2026-07-21

- Sun card: dropped the redundant "Sun" label and enlarged the sunrise/
  sunset icons (`min(7vw,40px)` -> `min(11vw,64px)`) -- at the old size the
  only visual difference between the two (a small up/down notch in the
  horizon line) was too subtle to read at a glance.

## [1.0.15] - 2026-07-21

- Home dashboard layout tweaks: more top margin, outdoor temperature moved
  to the middle of the hero row (between the rain/humidity stats and the
  clock), and the Sun card now shows sunrise/sunset icons with the times
  underneath instead of one combined text value.
- Found and fixed a real bug while adding the sunrise/sunset icons: their
  vendored artwork crops the sun via an internal SVG `<mask>`, which
  silently fails to apply when referenced from inside a `<symbol>`
  instantiated via `<use>` in this page's icon sprite. Fixed by baking the
  horizon crop directly into the icon geometry instead of relying on
  `<mask>`/`<clipPath>`. The same latent bug likely affects
  `partly-cloudy-day/night` and `thunderstorms-day/night` too, just
  invisibly (a cloud shape drawn on top happens to cover the same region) --
  flagged in docs/home-dashboard.md as a known risk, not yet fixed there.

## [1.0.14] - 2026-07-21

- Turn the home dashboard into an installable PWA: "Add to Home Screen" on
  the iPad now launches standalone (no Safari chrome), via a web app
  manifest and Apple-specific meta tags -- no service worker, since iOS
  standalone display doesn't need one and this page already handles
  offline/fetch-failure gracefully. A sun-glyph app icon (matching the
  vendored "clear-day" icon's amber tone) is generated once via a local
  Pillow script and written as real PNG files every cron run (not `data:`
  URIs, to avoid a known Mobile Safari `apple-touch-icon` reliability
  quirk). No deploy.sh/nginx changes needed -- confirmed live via `curl`.

## [1.0.13] - 2026-07-21

- Fill the empty space between the outdoor temp and the clock with chance
  of rain and outdoor humidity, sized to match the clock's font. Both
  reuse data already present in `data.json` (outdoor humidity, and the
  first forecast period's precipitation probability as "now") -- no new
  backend fields needed.

## [1.0.12] - 2026-07-21

- Replace the home dashboard's NWS-hotlinked forecast icons with a locally
  vendored set (Meteocons, flat style, MIT licensed) -- confirmed usable
  after the user pointed at meteocons.com and picked "flat" from a 4-style
  comparison. Icons are embedded once as an SVG `<symbol>` sprite in
  `index.html`; the forecast strip references them by id, so the 60-second
  `data.json` refresh only ever carries a small category string.
- Added `home_dashboard/weather_icons.py` to map NWS's forecast-icon
  condition codes to the vendored icon set, per NWS's own recommendation
  for their deprecated `/icons` endpoint ("map codes to custom graphics
  locally"). Found and fixed two real bugs while wiring this up against
  live data: NWS's actual API returns condition-code orderings
  (`tsra_sct`, `tsra_hi`) that don't match its own documented vocabulary
  (`scttsra`, `hi_tsra`), and a URL-parsing bug where the `icons` path
  segment was being classified as a spurious condition code, silently
  outranking real "clear"/"partly-cloudy" results in the severity ranking.
  Both were silently turning every non-cloudy forecast period into
  "cloudy" until caught by comparing against real NWS API responses.
- Added x/y axis labels (time and temperature) to the 12-hour outdoor
  temperature sparkline, per user feedback.

## [1.0.11] - 2026-07-21

- Home dashboard visual updates based on real usage feedback: swapped the
  clock and outdoor-temp hero positions (clock now smaller, secondary);
  added the Eve Weather sensor's own battery percentage; added NWS's own
  per-period condition icons to the forecast strip; added a 12-hour
  outdoor-temperature sparkline (client-side rendered from `data.json`,
  since the page never reloads itself after first load).
- Confirmed the actual iPad is stuck on iPadOS 15.8.8, below the 16.4
  Wake Lock API threshold -- added the NoSleep.js-style silent looping
  video fallback (a 1.7KB base64-embedded clip) for pre-Wake-Lock Safari.
- Fixed the same rsync `--delete`-deletes-`cron.log` bug (previously found
  and fixed in `energy_report/deploy.sh`) in `home_dashboard/deploy.sh`,
  which hadn't carried the same exclude over when first written.

## [1.0.10] - 2026-07-21

- Add `home_dashboard/`, a cron-generated home dashboard replacing an aging
  iPad's Carrot Weather app: Eve Weather outdoor temp, Nest indoor temp/
  setpoint, NWS forecast highs/lows and rain timing, sunrise/sunset, a live
  clock, and an A/C+EV usage-today estimate. Deployed live at
  `/dashboard/`. See `docs/home-dashboard.md` for the full writeup,
  including two real surprises hit along the way: `sun.sun`'s attributes
  are never persisted to HA's recorder DB, and domus's apt-installed
  `astral` is a much older major version with a completely different API
  than initially developed against.
- Added `get_latest_state()` and `get_latest_attributes()` to
  `energy_report/ha_recorder.py` -- small, generic reads shared by both
  packages now that `home_dashboard` imports `energy_report` as a sibling.

## [1.0.9] - 2026-07-21

- Switch the TOU report's outdoor-temperature source from NWS (nearest
  station) to a physical Eve Weather sensor mounted at the house
  (`sensor.eve_weather_20ebs9901_temperature`), commissioned via Matter
  multi-admin sharing from Alexa. A plain `sensor` entity rather than a
  `weather` entity, so this reads via `get_numeric_sensor_samples()`
  instead of `get_weather_temperature_samples()`.

## [1.0.8] - 2026-07-18

- Fix the "Data as of" header timestamp showing UTC instead of local time
  -- it's derived from the archive's `fetched_at` field (stored in UTC) and
  was never converted before display, unlike the footer's "Generated"
  timestamp which already used local time correctly.

## [1.0.7] - 2026-07-17

- Add and configure HA's built-in NWS (National Weather Service) integration
  on domus (station KSLC), and switch the TOU report's outdoor-temperature
  chart to read from it instead of Met.no -- NWS reports a real METAR/ASOS
  ground-station observation for "current conditions," while Met.no is a
  pure forecast-model value with no station feed.
- Documented a planned domus relocation (basement -> family room) in
  hardware.md, and a physical outdoor weather sensor (e.g. Eve Weather) in
  roadmap.md Phase 3, both blocked on Thread border router availability.

## [1.0.6] - 2026-07-17

- Add an "Outdoor temperature vs. usage" chart to the TOU report, comparing
  daily average outdoor temperature (from `weather.forecast_home`'s
  `temperature` attribute) against total daily usage and A/C-specific usage,
  both in kWh (tooltip also shows the A/C bar's equivalent runtime hours).
- New `get_weather_temperature_samples()` in `ha_recorder.py`, reading a
  weather entity's `temperature` attribute via `state_attributes` (weather
  entities store condition strings in their `state` column, not the
  reading itself).

## [1.0.5] - 2026-07-16

- Add a "Total" line to the usage breakdown chart's tooltip (sum of A/C, EV,
  and other/baseline for that day), via Chart.js's `tooltip.callbacks.footer`.
- Fix `deploy.sh`: its rsync `--delete` was deleting domus's `cron.log` on
  every redeploy since it wasn't excluded like `output/` was -- discovered
  when this deploy wiped the log. Added `--exclude 'cron.log'`.

## [1.0.4] - 2026-07-16

- Regenerate the TOU report every 2 hours instead of once daily, so it
  isn't a full day stale whenever it happens to run before RMP's own
  archive updates for that day. (Root cause of the staleness this was
  fixing: domus's OS clock was set to Europe/London instead of
  America/Denver, shifting cron's actual fire time by 7 hours from what
  was intended -- fixed at the OS level separately; this change makes the
  report robust to that kind of clock/scheduling drift regardless.)

## [1.0.3] - 2026-07-15

- Rename the TOU report's "Difference" KPI card to "Estimated TOU Penalty"
  or "Estimated TOU Savings" depending on sign, and color the value red
  (cost) or green (savings) to match the sensitivity table's convention.

## [1.0.2] - 2026-07-15

- Show units (kWh) in the TOU report's chart tooltips, matching the y-axis
  labels (Chart.js doesn't apply an axis tick formatter to tooltips
  automatically).

## [1.0.1] - 2026-07-15

- Right-align the TOU report's sensitivity table "Annual Impact" header to
  match its already-right-aligned data cells.

## [1.0.0] - 2026-07-15

Baseline release, capturing everything already deployed and in active use
on domus:

- Custom Rocky Mountain Power Home Assistant integration
  (`custom_components/rocky_mountain_power/`) — reverse-engineered Azure B2C
  auth and client-side RSA-4096/AES-GCM request encryption, hourly usage
  imported as HA external statistics plus a raw JSON archive. See
  [docs/rmp-integration.md](docs/rmp-integration.md).
- Daily Energy Story dashboard (apexcharts-card) combining RMP power,
  temperature, A/C, and EV charging on one full-width panel view.
- RMP Standard-vs-Time-of-Use cost comparison report (`energy_report/`) — a
  cron-generated static HTML report disaggregating usage into A/C, EV
  charging (per car), and baseline load, comparing observed/projected costs
  under both rate plans, and a per-lever sensitivity table (e.g. delaying EV
  charging, reducing on-peak A/C runtime). Deployed to domus, served via
  nginx at `/energy-report/`. See [docs/tou-report.md](docs/tou-report.md).
