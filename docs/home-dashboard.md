# Home dashboard: a Carrot Weather replacement

A cron-generated static page (`home_dashboard/`) replacing an aging iPad's
"Carrot Weather" app with the house's own real sensors: Eve Weather's
outdoor temperature, the Nest thermostat's indoor temperature/setpoint, NWS
forecast highs/lows and rain timing, sunrise/sunset, a live clock, and an
A/C+EV usage-today estimate. Deliberately excludes Carrot's moon phase,
golden/blue hour, and photography-timing chrome -- none of it requested.

## Why this exists

The user wanted their own data on an always-on glanceable display instead
of a generic weather app -- same underlying motivation as the TOU report
(`docs/tou-report.md`): once real sensors and HA integrations exist, a
purpose-built page beats a third-party app that can't see any of it.

The real design constraint is usage data: RMP's own archive
(`energy_report/`) lags ~2 days and can never show "today." The only
genuinely live-observable usage signals anywhere in this project are A/C
runtime and EV charging -- so this shows an explicitly-labeled **"A/C + EV
usage today (est.)"**, never implying it's total house usage, which needs
RMP's actual meter reading to know.

## Real findings from building this (not assumptions)

- **`sun.sun`'s rich attributes are never recorded.** `next_rising`,
  `next_setting`, `elevation`, `azimuth` -- confirmed live against 5+
  historical rows, every one holding only `friendly_name`. HA's recorder
  apparently excludes them (they'd otherwise churn constantly). So
  sunrise/sunset is computed independently via `astral`, not read from HA
  at all.
- **`astral`'s API changed completely between major versions, and domus
  only has the old one.** Developed initially against `astral` 3.x
  (`LocationInfo` + `astral.sun.sun()`, installed via pip locally) --  but
  domus's apt-installed `python3-astral` is **1.6.1**, a totally different
  API (`Location` class with a `.sun()` *method*, pytz-based return values
  instead of stdlib `zoneinfo`). `sun_times.py` is written against the
  actual installed 1.6.1 API; the local dev venv is pinned to the same
  version specifically so this mismatch can't silently reappear. Chose
  apt over `pip install --break-system-packages` to stay consistent with
  how `requests` is already an apt-installed system package here, not a
  pip one.
- **Forecast highs/lows come from NWS's public API directly, not HA's
  `weather.get_forecasts`.** Modern HA moved forecast data out of the
  recorder/state-attributes model into a live service-call-only mechanism,
  which would need a long-lived access token to reach from outside HA --
  the same token-vs-manual-step tradeoff already decided against for
  Matter device commissioning. `api.weather.gov`'s own forecast endpoint
  needs no key, just the same contact-identifier convention already used
  for the NWS station lookup, and returns day/night periods with
  temperature (that period's high or low), a short condition description,
  and precipitation probability directly.
- **Live updates without a running server or jarring reloads.** The TOU
  report's `<meta http-equiv="refresh">` would cause a visible flash every
  cycle -- wrong for an always-on display. Instead, cron (every 2 minutes)
  writes both `index.html` (the shell, embedding an initial data snapshot
  so the first paint isn't blank) and a small `data.json`; client-side JS
  refetches `data.json` every 60 seconds and updates the DOM in place, and
  the clock itself ticks every second off the browser's own clock, no
  server round-trip at all.
- **Keeping the iPad's screen awake is a page-level concern, not a device
  setting.** The page requests the Screen Wake Lock API
  (`navigator.wakeLock.request('screen')`) on load and again on
  `visibilitychange` (Safari can silently release the lock when the tab is
  backgrounded, e.g. the iPad briefly locks, and doesn't restore it on its
  own). Needs Safari/iPadOS 16.4+; given the iPad is described as
  "ancient," its actual OS version should be checked before assuming this
  works -- an older fallback (a silent looping video, which iOS
  historically respects as a keep-awake signal) exists but was
  deliberately not built preemptively, only if the version check actually
  shows it's needed.

## File layout

- `forecast.py` -- NWS forecast API client (plain `requests`)
- `sun_times.py` -- independent sunrise/sunset via `astral` 1.x
- `usage_today.py` -- "since local midnight" A/C+EV estimate, reusing
  `energy_report.ha_recorder`'s `get_binary_sensor_intervals()`/
  `get_numeric_sensor_samples()` and `energy_report.disaggregation`'s
  `ac_kwh_for_hour()`/`ev_kwh_for_hour()`/`AC_ESTIMATED_KW` directly --
  same math as the TOU report's own disaggregation, just queried live
  against "now" instead of the RMP archive's lagging dates
- `render.py` -- HTML/CSS/JS shell + `data.json` builder
- `generate_dashboard.py` -- CLI entry point, atomic writes, cron target
- `deploy.sh` -- mirrors `energy_report/deploy.sh`'s pattern exactly

Two small, generic reads were added to `energy_report/ha_recorder.py`
itself (shared across both packages, since `home_dashboard` imports it as
a sibling): `get_latest_state()` and `get_latest_attributes()` -- "what's
the most recent raw state/attributes for this entity," used here for the
NWS condition string and the climate entity's current temperature/setpoint/
hvac_action, following the same gap-aware conventions (`None`/`{}` for
missing data, never fabricated) as every other reader in that module.

## Setup

1. `home_dashboard/deploy.sh` -- rsyncs the package to
   `domus:/opt/home-intelligence/home_dashboard/` and prints the remaining
   manual steps.
2. `sudo apt-get install -y python3-astral` on domus (one-time; `requests`
   is already present the same way).
3. Cron entry running `python3 -m home_dashboard.generate_dashboard` every
   2 minutes (module invocation, cwd `/opt/home-intelligence` -- both this
   package's relative imports and its `energy_report` sibling import
   require it).
4. `/dashboard/` nginx location block, alongside the existing
   `/energy-report/` one.
5. Recreate (not restart) the `ha-proxy` container with one more bind
   mount for this package's output directory.

## Known risks / things to watch

- **A/C + EV usage today is an estimate of exactly those two loads, not
  total house usage** -- explicitly captioned as such on the page itself.
  Same nameplate-based A/C draw caveat as the TOU report.
- **Astral version drift risk**: if domus's apt packages ever update
  `python3-astral` to a 2.x/3.x release, `sun_times.py`'s `Location`/
  `.sun()` calls would break (different API entirely). Worth a quick
  check after any `apt upgrade` touches this package.
- **iPad OS version unconfirmed** -- Wake Lock API needs 16.4+; check
  Settings -> General -> About on the actual device before relying on it,
  and add the video-fallback trick only if that check shows it's actually
  needed.
- **NWS's forecast endpoint is grid-point-specific**
  (`gridpoints/SLC/103,174/forecast`), hardcoded for the house's current
  location -- would need updating if the reference point ever changes.

## Status

- [x] `forecast.py`
- [x] `sun_times.py`
- [x] `usage_today.py`
- [x] `render.py`
- [x] `generate_dashboard.py`
- [x] Unit tests (17 passing, plus 6 new shared-reader tests in
      `energy_report`'s own suite -- 79 total across both packages)
- [x] `deploy.sh`
- [x] Deployed to domus and verified end-to-end (cron entry live, nginx
      location added, `ha-proxy` container recreated with the new bind
      mount, confirmed live via `curl` against both `index.html` and
      `data.json`)
- [ ] Verified on the actual iPad (screen wake behavior, visual layout at
      the device's real screen size/orientation)
