# Changelog

All notable changes to this project are documented here. Version is tracked
in the root `VERSION` file (this project has no single package manifest, so
`VERSION` is the canonical source of truth; the RMP HA integration's own
`manifest.json` version is independent, scoped to Home Assistant's own
per-integration update tracking).

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
