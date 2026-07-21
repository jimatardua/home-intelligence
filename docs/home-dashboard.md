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
  own). Needs Safari/iPadOS 16.4+ -- **confirmed this iPad (an Air 2) is
  stuck on 15.8.8**, well below that, so Wake Lock isn't available at all
  here. Added the pre-Wake-Lock fallback the NoSleep.js library popularized:
  a tiny (1.7KB), silent, looping, `muted`/`playsinline` black video,
  base64-embedded directly in the page (no separate asset file) rather than
  built preemptively -- only added once the real device's OS version showed
  it was actually needed, per the original plan. Verified it loads and
  decodes correctly in-browser (`readyState=4`, `duration=2`, no error);
  the actual keep-awake behavior can only be confirmed on the real iPad
  itself, not this dev environment's browser.
- **Client-side `data.json` polling means the initial HTML render is a
  one-time snapshot, not a live view.** The page loads once and never
  reloads itself (that's the whole point of a kiosk display) -- so
  anything baked only into the server-rendered `index.html` would go stale
  forever after first load. This matters concretely for the 12-hour
  temperature sparkline added later: it's built from raw sample points in
  `data.json` and redrawn client-side into an inline SVG on every 60-second
  refresh, not rendered server-side into static markup.

## File layout

- `forecast.py` -- NWS forecast API client (plain `requests`); each period's
  NWS icon URL is mapped to a local icon category via `weather_icons.py`
  before it ever reaches `render.py`
- `weather_icons.py` -- maps NWS's forecast-icon condition codes (`skc`,
  `bkn`, `tsra`, ...) to one of the 14 locally vendored icon categories;
  pure function, no I/O, easy to test against NWS's real vocabulary directly
- `icons.py` + `icons/*.svg` -- the vendored icon set itself (Meteocons,
  flat style, MIT licensed -- see "Icon source" below)
- `sun_times.py` -- independent sunrise/sunset via `astral` 1.x
- `usage_today.py` -- "since local midnight" A/C+EV estimate, reusing
  `energy_report.ha_recorder`'s `get_binary_sensor_intervals()`/
  `get_numeric_sensor_samples()` and `energy_report.disaggregation`'s
  `ac_kwh_for_hour()`/`ev_kwh_for_hour()`/`AC_ESTIMATED_KW` directly --
  same math as the TOU report's own disaggregation, just queried live
  against "now" instead of the RMP archive's lagging dates
- `temp_history.py` -- last-12h outdoor temperature readings for the
  sparkline, reusing `get_numeric_sensor_samples()` directly (same reader,
  different time window than the current-value read)
- `render.py` -- HTML/CSS/JS shell + `data.json`/`manifest.json` builder,
  plus the base64-embedded PWA icon constants
- `generate_dashboard.py` -- CLI entry point; every cron run atomically
  writes `index.html`, `data.json`, `manifest.json`, `apple-touch-icon.png`,
  and `icon-512.png` (the latter three are static/PWA-related but still
  regenerated every run, since `output/` is entirely cron-owned with no
  other mechanism to place a file there)
- `deploy.sh` -- mirrors `energy_report/deploy.sh`'s pattern exactly (also
  hit and fixed the exact same rsync `--delete`-deletes-`cron.log` bug
  found and fixed in `energy_report/deploy.sh` -- forgot to carry the
  exclude over when this file was first written)

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

## Visual iteration (after first deploy, based on user feedback)

- Swapped the hero layout: outdoor temp/condition now on the left (large),
  the clock moved to the right at 40% of its original size (user's own
  ask -- the clock was originally the largest, most prominent element;
  outdoor conditions took priority once seen in practice).
- Added the Eve Weather sensor's own battery percentage (HA already
  surfaces it as `sensor.eve_weather_20ebs9901_battery`, a plain
  percentage sensor -- no new data-fetching pattern needed).
- Added NWS's own per-period condition icons to the forecast strip, via
  plain `<img>` tags pointing at NWS's icon URLs -- no local icon set or
  condition-to-icon mapping to build or maintain. **Superseded** by the
  vendored icon set below after a second round of feedback asked for a
  cleaner icon style.
- Added the 12-hour outdoor temperature sparkline described above.

### Icon source: NWS hotlinked -> Meteocons vendored locally

Second-round feedback asked for cleaner-looking forecast icons (pointing at
Apple's Weather app as a style reference) and for x/y axis labels on the
sparkline. The icon request needed a real licensing check first: Apple's
own icon artwork on `support.apple.com` is proprietary and not reusable.
Landed on [Meteocons](https://meteocons.com) (`basmilius/meteocons` on
GitHub) instead -- confirmed MIT licensed via the repo's actual `LICENSE`
file, 500+ icons across 4 styles (fill, flat, line, monochrome). Showed the
user a side-by-side comparison of all 4 styles; **flat** was the pick.

- **Vendored, not hotlinked or CDN-loaded.** The 14 icon categories this
  house's forecasts actually need are downloaded once and stored as
  `<symbol>` fragments under `icons/*.svg` (each ~0.3-9KB, ~72KB total).
  Same "the page must be self-contained" reasoning as the NoSleep video:
  an always-on kiosk display shouldn't have a per-refresh dependency on
  NWS's icon server (which is itself marked deprecated,
  see below) or a third-party CDN.
- **One sprite, baked into `index.html` once.** All 14 `<symbol>`s are
  concatenated into a single hidden `<svg>` block, embedded by `render_html()`
  at first load. The forecast strip then references icons by id
  (`<use href="#icon-clear-day">`); `data.json`'s 60-second refresh only ever
  carries the small category string, not repeated SVG markup -- consistent
  with keeping that polling payload lightweight.
- **NWS's icon condition codes are mapped locally, per NWS's own advice.**
  NWS's `/icons` endpoint is marked deprecated (though still functional, no
  removal timeline --
  [weather-gov/api#557](https://github.com/weather-gov/api/discussions/557)),
  and NWS's own recommended long-term approach is "map icon codes to custom
  graphics locally." `weather_icons.py` does exactly that: classifies each
  condition segment in the URL by substring match (rather than exact
  lookup -- see the real bug this avoided, below), then keeps the most
  severe classification when a period packs multiple segments together
  (e.g. `bkn/tsra_hi,40` -- cloudy early in the period, thunderstorms
  later), always returning a valid icon rather than raising on an
  unrecognized code. An approximate icon is harmless in a way a fabricated
  sensor reading would not be, and NWS's condition vocabulary isn't a
  fixed, versioned contract.
- **NWS's documented vocabulary doesn't match what the live API actually
  returns.** [weather.gov/forecast-icons](https://www.weather.gov/forecast-icons)
  lists `hi_tsra` and `scttsra` for thunderstorm variants; real forecast
  responses captured live during development used `tsra_hi` and
  `tsra_sct` instead (modifier and base swapped). An exact-match mapping
  built against the documented codes silently classified every real
  thunderstorm period as plain "cloudy." Fixed by classifying each code by
  substring (`"tsra" in code`) instead of exact equality -- catches either
  ordering, and any other NWS combines-with-an-underscore variant, without
  needing to enumerate every real-world permutation by hand.
- **A related parsing bug surfaced while fixing that:** the live URL shape
  is `.../icons/land/day/skc`, and the `icons` path segment isn't a
  condition code -- an earlier version that classified every segment after
  `land`/`day`/`night` (rather than anchoring on the `day`/`night` marker
  itself) picked up `icons` as a spurious extra classification, which fell
  back to the default "cloudy" category and then *outranked* the real
  "clear" classification in the severity ranking. Fixed by anchoring on
  the `day`/`night` marker's index and treating everything after it as
  condition codes, regardless of how many fixed segments precede it.
- Some categories (`cloudy`, `rain`, `snow`, `sleet`, `drizzle`, `fog`,
  `smoke`, `wind`) have no day/night variant in Meteocons' set (confirmed
  via HTTP HEAD checks -- `rain-night` 404s, for example); only `clear`,
  `partly-cloudy`, and `thunderstorms` do.

### Chance of rain and humidity in the hero row

There was a lot of unused space between the outdoor temp block and the
clock once the layout got swapped around. Filled it with chance of rain
and outdoor humidity, sized to match the clock's own font size so it
reads as part of the same hero row rather than a smaller secondary detail.
Neither needed a new data source: humidity was already in `data.json`
(`outdoor_humidity_pct`, from the same Eve Weather sensor as the
temperature) but never rendered anywhere; chance of rain reuses the first
forecast period's `precip_probability_pct` (`d.forecast[0]`) -- that
period already represents "now" (it's "Today" during the day, "Tonight"
after dark), so no new backend field was needed for it either.

### Sparkline axis labels

Added a gridline + label at the min and max temperature (y-axis) and a
time label at the start, middle, and end of the window (x-axis), computed
client-side in `drawSparkline()` from the actual `data.json` history array
-- not hardcoded to a 12-hour assumption, so it still labels correctly if
the window has less data than that (e.g. shortly after a restart).

### Hero row: more top margin, temperature moved to the middle

The temperature felt crowded against the very top edge once the PWA
safe-area padding shipped (still `max(2vh, ...)` at the time) -- bumped the
body's top padding to `max(4vh, ...)`. Separately, moved the outdoor temp/
condition/battery block from the left position to the middle of the hero
row (between the rain/humidity stats and the clock), centering the single
largest element instead of pinning it to the left edge; `.outdoor` picked
up `text-align:center` to match its new position.

### Sun card: icons instead of a single combined time string

Replaced the "6:12 AM / 8:45 PM" single value with two icon+time pairs
(sunrise icon above the sunrise time, sunset icon above the sunset time,
both in a smaller font than the old combined value). Needed two new
vendored icons -- Meteocons' `sunrise`/`sunset` (flat style, same MIT
source as the rest of the set) -- with the same horizon-line recolor
(`#202939` -> `#8b93a7`) already applied to keep it visible on the dark
background. Dropped the card's "Sun" label entirely -- the icons make it
obvious by context. At the icons' original size (`min(7vw,40px)`, matching
the forecast strip), the only visual difference between sunrise and
sunset -- a small up/down notch in the horizon line -- was too subtle to
read at a glance, so they're sized up to `min(11vw,64px)` now that the
label's removal freed up room in the card.

**A real, previously-latent bug surfaced while adding these**: Meteocons'
`sunrise`/`sunset` artwork crops the sun to "peeking above/below the
horizon" via an internal `<mask>`, referenced from inside the vendored
`<symbol>` and instantiated via `<use>` in the page's icon sprite -- and
that mask silently failed to apply in this exact setup (confirmed via a
side-by-side render: the full sun with all 8 rays showed through
completely uncropped, horizon line included, no visible masking effect at
all). Switching the crop mechanism to an SVG `<clipPath>` didn't help
either -- same failure. The other vendored icons that also use an internal
mask (`partly-cloudy-day/night`, `thunderstorms-day/night`) happen to
*look* correctly cropped anyway, but only by coincidence: their mask-cropped
region is also covered by an opaque shape drawn on top afterward (the
cloud), so whether the mask actually applied was never visually
observable. This means the same latent bug likely affects those icons
too, just invisibly.

Fixed for `sunrise`/`sunset` by abandoning `<mask>`/`<clipPath>` entirely
and baking the crop directly into the geometry instead: the sun's circle
was replaced with a flat-bottomed dome path (an SVG arc closed with a
straight chord at the horizon line's y-coordinate), and the three rays
that would extend past the horizon (down, lower-left, lower-right) are
simply omitted rather than drawn and clipped. No `url()` reference
involved at all, so there's nothing left for this bug to affect.

**Not yet fixed**: the same latent risk in the other masked icons. Since
their coincidental correctness only holds as long as the covering shape
(cloud) exactly matches the masked region, this is worth a closer look if
those icons are ever revised -- see "Known risks" below.

### Battery indicator moved to a fixed page corner

Originally sat directly under the outdoor temp/condition text; once that
block moved to the middle of the hero row, the battery percentage read as
oddly prominent (dead center of the screen) for a minor, infrequently-
interesting detail. Moved to `position:fixed` in the page's bottom-right
corner instead -- present but unobtrusive, out of the main content flow
entirely, using the same `env(safe-area-inset-*)` pattern as the body
padding for correctness on any device. No JS change needed: the element
kept its `id="battery"`, so `applyData()`'s existing update call didn't
need to change, only where that element sits in the page.

### PWA: installable, standalone, no Safari chrome

The user wanted to "Add to Home Screen" on the iPad and have it launch
without Safari's URL bar/toolbar, so it reads as a dedicated kiosk app
rather than a browser tab left open. iOS's standalone-display behavior is
driven entirely by Apple-specific meta tags and a web app manifest, not a
service worker.

- **No service worker, deliberately.** iOS's "Add to Home Screen" standalone
  mode doesn't need one -- that's purely the `apple-mobile-web-app-capable`
  meta tag. Service workers matter more for Chrome/Android's stricter
  installability heuristics and for actual offline asset caching, neither
  of which this page needs: it already keeps last-known-good data on a
  transient `data.json` fetch failure, and is deliberately designed to
  never reload once loaded. A service worker would add cache-versioning/
  staleness risk for a kiosk that's always on the home network, for no
  real benefit -- considered and rejected.
- **Icons are real files, not `data:` URIs, on purpose.** Mobile Safari has
  a long-standing, widely-reported quirk where `apple-touch-icon` doesn't
  reliably honor `data:` URIs (it uses a different icon-fetch path than
  normal resource loading, and has been observed falling back to a
  screenshot or a default icon instead). Since the actual home-screen icon
  is the single riskiest unknown in this whole change and iOS 15.8 is the
  exact target, it isn't worth betting on that quirk. Instead: a sun-glyph
  icon (amber circle + rays, matching the vendored "clear-day" Meteocons
  icon's own color, derived from that SVG's actual fill rather than
  re-hardcoded) is drawn once via a local Pillow script -- a dev-machine-only
  tool, never a domus dependency, the same relationship `ffmpeg` has to the
  NoSleep video below -- at 180x180 and 512x512, base64-embedded as
  constants in `render.py` (same storage pattern as `_NOSLEEP_VIDEO_BASE64`),
  and decoded to real files (`apple-touch-icon.png`, `icon-512.png`) by
  `generate_dashboard.py` every cron run, referenced by plain relative URLs.
- **`manifest.json` is rendered fresh every run** via `render_manifest_json()`
  -- no live data involved, but generating it in Python lets it share
  `render.py`'s `BG_COLOR` (and friends) with the CSS instead of hardcoding
  the same hex value in two places.
- **`"orientation": "landscape"`** is set to match how the iPad is actually
  mounted, but iOS Safari has never honored this manifest field for
  standalone web apps (that's a Chrome/Android behavior) -- it's included
  because it's spec-correct and free, not because it does anything on the
  real device. The landscape lock in practice comes entirely from the
  physical mount and the device's own rotation lock.
- **Safe-area padding** (`env(safe-area-inset-*)`, requiring
  `viewport-fit=cover` on the viewport meta tag -- without it every inset
  resolves to `0` regardless of CSS) is real and correct, but the iPad
  Air 2 has a physical home button and no notch or rounded display corners,
  so every inset is `0` on this exact device today. This is forward-compat
  for a different/future device, not a fix for any clipping actually
  observed on the current hardware.
- **No deploy.sh/nginx/docker changes needed.** All three new outputs
  (`manifest.json`, `apple-touch-icon.png`, `icon-512.png`) land in the same
  cron-written `output/` directory the existing `location /dashboard/`
  block already serves; nginx's default `mime.types` already maps
  `.json`/`.png` correctly. Confirmed live via `curl`, not just assumed.

## Known risks / things to watch

- **A/C + EV usage today is an estimate of exactly those two loads, not
  total house usage** -- explicitly captioned as such on the page itself.
  Same nameplate-based A/C draw caveat as the TOU report.
- **Astral version drift risk**: if domus's apt packages ever update
  `python3-astral` to a 2.x/3.x release, `sun_times.py`'s `Location`/
  `.sun()` calls would break (different API entirely). Worth a quick
  check after any `apt upgrade` touches this package.
- **NoSleep-video fallback verified in-browser, not yet on the real
  iPad** -- the video itself is confirmed to load/decode correctly, but
  whether it actually prevents iPadOS 15.8's screen from sleeping can only
  be confirmed on the physical device.
- **NWS's condition-code vocabulary isn't a versioned contract.** If NWS
  ever adds a new code `weather_icons.py` doesn't recognize, it falls back
  to `DEFAULT_ICON_CATEGORY` ("cloudy") rather than crashing -- worth
  occasionally diffing against
  [weather.gov/forecast-icons](https://www.weather.gov/forecast-icons) if a
  forecast period's icon looks obviously wrong.
- **NWS's forecast endpoint is grid-point-specific**
  (`gridpoints/SLC/103,174/forecast`), hardcoded for the house's current
  location -- would need updating if the reference point ever changes.
- **PWA icon/manifest behavior confirmed via browser inspection and `curl`
  only, not yet via an actual "Add to Home Screen" on the real iPad** --
  same "confirmed in-browser, not on-device yet" pattern already applying
  to the NoSleep-video fallback above. Specifically unverified: whether
  `apple-touch-icon.png` actually becomes the home-screen icon (rather than
  a fallback screenshot -- the exact risk avoiding `data:` URIs was meant to
  mitigate, but still only provable on-device); whether the launched app is
  genuinely chrome-free/standalone; whether `black-translucent` looks right
  against this device's actual status bar.
- **`partly-cloudy-day/night` and `thunderstorms-day/night` likely share
  the same latent internal-`<mask>`-via-`<use>` bug found while building
  the sunrise/sunset icons** (see above) -- their masks may be silently
  failing exactly like sunrise/sunset's did, just masked (no pun intended)
  by a coincidence of the artwork: the cloud shape drawn afterward happens
  to cover the same region the mask was supposed to crop. Not yet fixed,
  since it isn't visibly broken today -- worth converting to baked-in
  geometry (like sunrise/sunset) if these icons are ever revised, rather
  than trusting the coincidence to keep holding.

## Status

- [x] `forecast.py` (+ icon categories via `weather_icons.py`)
- [x] `sun_times.py`
- [x] `usage_today.py`
- [x] `temp_history.py`
- [x] `render.py` (layout swap, battery, icons, sparkline + axis labels,
      video fallback, PWA manifest/icons/meta tags, hero reorder + top
      margin, sunrise/sunset icons on the Sun card)
- [x] `generate_dashboard.py`
- [x] `weather_icons.py` + vendored `icons/*.svg` (Meteocons, flat style,
      MIT licensed, replacing the original NWS-hotlinked `<img>` icons)
- [x] PWA: `manifest.json`, `apple-touch-icon.png`, `icon-512.png` --
      installable/standalone on iOS, no service worker (see "PWA" above)
- [x] Unit tests (47 passing in `home_dashboard`, 62 in `energy_report` --
      109 total across both packages)
- [x] `deploy.sh`
- [x] Deployed to domus and verified end-to-end (cron entry live, nginx
      location added, `ha-proxy` container recreated with the new bind
      mount, confirmed live via `curl` against `index.html`, `data.json`,
      `manifest.json`, and both icon PNGs -- all real fields, including the
      new PWA outputs, populated/served correctly)
- [ ] Verified on the actual iPad (screen wake behavior via the video
      fallback, "Add to Home Screen" installability and standalone
      launch behavior, visual layout at the device's real screen
      size/orientation)
