# Sensus Analytics (Salt Lake City water) custom integration

A custom Home Assistant integration (`custom_components/sensus_analytics/`)
that pulls daily and hourly water-usage data from Salt Lake City Public
Utilities' digital-meter customer portal
(`my-slc.sensus-analytics.com`) into HA.

## Why this exists

SLC Public Utilities has no official public usage API. Its residential
smart-meter portal runs on **Sensus Analytics**, a white-label AMI
(advanced metering infrastructure) platform used by 70+ utilities under
their own subdomains. The HA community has already reverse-engineered its
login and data endpoints and built
[`zestysoft/sensus_analytics_integration`](https://github.com/zestysoft/sensus_analytics_integration)
(Apache-2.0, actively maintained). This integration is a **fork of that
project**, vendored directly into this repo (matching
`custom_components/rocky_mountain_power`'s placement, not a separate
GitHub fork) and patched — see "What was patched" below.

**Status: deployed to domus and verified against the live portal
(2026-10-10).** The meter was upgraded to digital in late summer 2026; the
portal account took a few weeks to become usable (it was blocked on
credentials in September — the Sensus Analytics login is separate from the
main utility account). See "Live verification" below for what was
confirmed, and the bug and gaps it surfaced.

## How Sensus Analytics' portal actually works

Confirmed by reading the upstream fork's source (not just its README):

### Login

Standard Spring-Security form login, not OAuth/B2C like RMP:

```
POST {base_url}/j_spring_security_check
  form body: j_username=<username>&j_password=<password>
```

Success is a **302 redirect**; any other status code means the credentials
were rejected. The session cookie set on that response is what
authenticates every subsequent call.

### Daily usage

```
POST {base_url}/water/widget/byPage
  json body: {"group": "meters", "accountNumber": <account>, "deviceId": <meter>}
```

Response shape: `{"widgetList": [{"data": {"devices": [{...}]}}]}` — the
single object at `widgetList[0].data.devices[0]` carries `dailyUsage`,
`usageUnit`, `meterId`, `meterAddress1`, `meterLat`/`meterLong`,
`lastRead` (ms timestamp), `latestReadUsage` (cumulative odometer), and
`billingUsage`.

### Hourly usage

```
GET {base_url}/water/usage/{account}/{meter}
  params: start=<ms>, end=<ms>, zoom=day, page=null, weather=1
```

Response shape: `{"operationSuccess": bool, "data": {"usage": [[units...], [ts, usage, rain, temp], ...]}}`
— the first inner list is a 3-element unit header (e.g.
`["GAL", "INCHES", "FAHRENHEIT"]`), every entry after that is one hour's
`[timestamp_ms, usage, rain, temp]`.

Both shapes are confirmed only against what the reverse-engineering thread
and the upstream fork's own code capture — a different utility's Sensus
instance could plausibly differ. `api.py` raises `UnexpectedResponse`
rather than a bare `KeyError`/`IndexError` whenever a response doesn't
match, so a shape mismatch surfaces as a clear coordinator error instead of
a stack trace.

## File layout

Mirrors `custom_components/rocky_mountain_power`'s shape:

- **`api.py`** — `SensusAnalyticsClient`, a synchronous client (`requests`,
  own private `Session`, never HA's shared one). `login()`,
  `get_daily_data()`, `get_hourly_data_raw()`. `SensusAnalyticsError` base
  with `CannotConnect`/`InvalidAuth`/`UnexpectedResponse` subclasses — this
  is now the **only** place in the package that makes an HTTP request (see
  "What was patched" #2).
- **`const.py`** — endpoints, `UPDATE_INTERVAL` (30 min default — see
  "Deferred" below).
- **`coordinator.py`** — `DataUpdateCoordinator` subclass. Logs in, fetches
  daily data, then best-effort fetches yesterday's hourly data (a failure
  there logs a warning but doesn't fail the whole update, since daily data
  — the primary sensors — already succeeded). The hourly JSON-shape
  parsing is unchanged from the upstream fork; it was already reasonable.
- **`config_flow.py`** — single-step form: credentials, account/meter
  number, and billing-tier pricing (still one flat schema — see
  "Deferred"). Validates login via `api.py` before creating the entry.
  Options flow re-validates the same way before applying a change.
- **`__init__.py`** — standard `async_setup_entry`/`async_unload_entry`,
  stores the coordinator on `entry.runtime_data`, registers an
  update-listener that reloads the entry when options change.
- **`sensor.py`** — 15 entities: daily usage, meter odometer, meter
  metadata (address/lat/long/ID), last-read timestamp, billing-period
  usage/cost, a flat daily-fee cost, and four "last hour"
  usage/rainfall/temperature/timestamp sensors. `_tiered_usage_cost()` and
  `_current_hour_entry()` are shared helpers extracted from duplicated
  logic found while porting this over (see "What was patched" #2).
- **`manifest.json`** — standard HA integration metadata.
- **`translations/en.json` / `strings.json`** — config-flow field labels,
  descriptions, and error strings. HA reads a *custom* integration's labels
  from `translations/en.json`; `strings.json` is the core-development
  convention this fork inherited. They must stay identical (enforced by
  `tests/test_translations.py`, since there's no build step generating one
  from the other). The tier-size fields' internal keys are still
  `tier1_gallons`/`tier2_gallons` (renaming would orphan stored config
  entries), but their *visible* labels say "size (in your Unit Type)" —
  see "Live verification" for why.
- **`LICENSE` / `NOTICE.md`** — Apache-2.0 attribution to the upstream
  fork; `NOTICE.md` lists every change made here.

## What was patched, and why

A source-level review of the upstream fork (not just its README) found
five real issues, all fixed here:

1. **Password shown in plaintext.** The setup form used a bare `str` field
   for the password, and the *options* (reconfigure) form pre-filled the
   real, current password back into that same unmasked field as its
   visible default. Both now use HA's masked
   `selector.TextSelector(..., type=TextSelectorType.PASSWORD)`. The
   options flow also now re-validates credentials the same way initial
   setup does (the original wrote unvalidated data straight to the config
   entry).
2. **The same login call implemented twice, in two different HTTP
   libraries** — `config_flow.py` used `aiohttp` to POST to
   `j_spring_security_check`; `coordinator.py` used `requests` to POST to
   the *same* endpoint with the *same* payload. Consolidated into
   `api.py`'s `SensusAnalyticsClient`, now the only file making an HTTP
   request (verified: `grep -rn "requests\.\|aiohttp\." custom_components/sensus_analytics/`
   only hits `api.py` and its own test). Two smaller duplications were
   found only while actually porting the code over, not during the
   original review: the tiered-pricing math was repeated (with one
   difference — a flat service fee) across two sensor classes, and four
   "last hour" sensors each independently re-implemented the same
   hour-matching search loop. Both factored into shared helpers in
   `sensor.py`.
3. **Dead code**: an `is_matching()` config-flow override that
   unconditionally `return False`d with an "implement if necessary"
   comment. Removed — this flow has no discovery source (Bluetooth,
   Zeroconf, etc.), only a user-initiated step, so HA never actually calls
   it.
4. **No tests at all.** Added `tests/test_api.py` (HTTP/auth logic, mocked
   `requests`), `tests/test_sensor.py` (the tiered-pricing and
   current-hour-lookup helpers, plus the unit-conversion mixin across
   every unit-pair combination), and `tests/test_config_flow.py`
   (credential-validation delegation, and static confirmation that the
   password field is genuinely a masked selector — not a bare `str` — and
   that `is_matching` is gone). Originally 40 tests; 47 now (see "Live
   verification" and "Running the tests").
5. **`update_interval` hardcoded to 5 minutes** despite Sensus data
   updating far less often per the community thread that first
   reverse-engineered this API. Moved to a named `UPDATE_INTERVAL`
   constant in `const.py`, default changed to 30 minutes — see "Deferred"
   for why this isn't tuned further yet.

Also modernized to `entry.runtime_data` (current HA convention, matching
`rocky_mountain_power` elsewhere in this repo) instead of the
`hass.data[DOMAIN][entry.entry_id]` dict pattern the upstream fork used.
This incidentally fixed a real bug: the original options flow called
`coordinator.async_request_refresh()` on the *existing* coordinator/client
after updating config data, so a changed username or password via options
never actually took effect (the old client instance, with old credentials
already baked in, kept being reused). The new update-listener triggers a
full `async_reload`, which reconstructs the client with the fresh
credentials.

## Live verification (2026-10-10)

Deployed to domus, added through HA's UI, and every sensor checked against
SLC's real portal (driven through a browser session Jim signed into himself;
credentials were never typed by the agent). The portal's own dashboard
calls the same `POST /water/widget/byPage` this integration does, so the
reverse-engineered endpoint and response shape are now confirmed live, not
just inferred from upstream's code.

**Confirmed matches:** billing-cycle usage (1.25 CCF, "Oct 9 2026 to
date"), daily usage (0.21 CCF), meter odometer (4677.81 CCF), meter ID,
address, and coordinates. Billing Cost equals `service_fee + tiered cost`
exactly, and the same tier math reproduced a real SLC bill's water line to
the cent ($199.98 for 33 CCF: `5×3.36 + 5×4.13 + 23×5.28 + 41.09`).

**Recommended SLC configuration** (derived from the 2026-09-14 charge
details, not the portal's displayed rates — see finding 3):

| Field | Value |
|---|---|
| Unit Type | `CCF` (the portal reports CCF natively) |
| Tier 1 size / price | `5` CCF / `3.36` per CCF |
| Tier 2 size / price | `5` CCF / `4.13` per CCF |
| Tier 3 price | `5.28` per CCF (everything above 10 CCF) |
| Service fee | `41.09` (water service fee, 1" meter, per cycle) |

### Findings

1. **Bug fixed: "Last Read" read the wrong field.** The sensor used the
   API's `lastRead`, which is a day-bucket marker (`2026-10-11T05:00Z` — in
   the future at 3 PM on 10/10), not a read time. The real one is
   `latestReadTime` (`2026-10-10T14:00Z` = 8:00 AM Denver), which matches
   the portal's own "Last read at 10/10/26 8:00 am". An inherited upstream
   bug, never caught because nobody had live data to compare against. Fixed,
   with tests using the real captured values; a missing `latestReadTime`
   reads as unknown rather than falling back to the marker.
2. **Tier fields are in whatever Unit Type is selected.** The cost helpers
   take a parameter named `usage_gallons`, but they're fed the
   already-converted value in the configured unit, so with `CCF` selected
   the tier sizes are CCF and the prices are per CCF. The fields' internal
   keys (`tier1_gallons`, ...) are unchanged to avoid orphaning stored
   config entries; only their visible labels/descriptions were corrected.
3. **The portal's displayed rates differ from the bill's.** The portal
   lists four tiers ($2.84 / $3.49 / $4.46 / $4.92 per CCF); the bill's
   rates for the first three are exactly 1.183× those ($3.36 / $4.13 /
   $5.28). The bill's are what's actually charged (verified to the cent),
   so those are configured.
4. **SLC has four tiers; this integration models three.** The tier-3/4
   boundary isn't readable from the portal (its dashboard chart uses a
   placeholder axis scale). Recent cycles (33–34 CCF) stay inside tier 3,
   so today's Billing Cost is accurate, but a heavy-irrigation month could
   cross into tier 4 and the sensor would understate it.
5. **Portal data lags real time by hours.** At 3 PM the latest read was
   from 8:00 AM that day ("Today: as of 8:00 am"). So "Daily Usage" means
   today *so far as of the last read*, not a full day, and 30-minute polling
   is probably more frequent than the data actually changes.
6. **"Last Hour" sensors are really "this hour yesterday".** The
   coordinator (unchanged from upstream) fetches *yesterday's* hourly data
   and matches it against the current clock hour; at 14:51 on 10/10 the
   "Last Hour Timestamp" read `2026-10-09 14:00`. There is no live same-day
   hourly signal from this integration.
7. **"Daily Fee" understates cost.** It prices a single day's usage against
   the *monthly* tier widths, so a normal day always lands in tier 1.
   "Billing Cost" is the accurate sensor. Upstream behavior, not changed.
8. **Billing cycles are the portal's, not calendar months** (the current
   cycle began Oct 9; the previous ran Sep 9 – Oct 8). `Billing Usage`'s
   `last_reset` is hard-coded to the first of the calendar month, which
   doesn't line up with that — a latent mismatch for long-term statistics,
   not yet addressed.

## Deferred (not done here, flagged for later)

- **Tier 4 support** — needs the tier-3/4 boundary (SLC's published rate
  schedule, or a bill that reaches block 4) plus one more price field.
- **Confirming `UPDATE_INTERVAL` against SLC's real cadence.** 30 minutes is
  a conservative guess; finding 5 suggests the data changes less often.
  Tune once real update timestamps have been observed over a day or two.
- **`Billing Usage` `last_reset`** aligned to the portal's billing-cycle
  start instead of the first of the month (finding 8).
- **Splitting billing/tariff config out of the credentials schema.** The
  config flow still mixes API credentials with billing-tier pricing fields
  in one flat schema, matching upstream. Splitting those (mirroring
  `energy_report`'s `billing.py`/`tariffs.py` separation elsewhere in this
  repo) is a real possible improvement but wasn't part of the actual ask.
- **Upstream issue #85** (historical backfill on first setup) — not needed
  for this use case.

## Setup

1. Deploy to domus (excluding tests/caches), then restart HA:

   ```
   rsync -av --delete --exclude __pycache__ --exclude tests --exclude .pytest_cache \
     custom_components/sensus_analytics/ \
     domus:/var/lib/homeassistant/homeassistant/custom_components/sensus_analytics/
   ssh domus "ha core check && ha core restart"
   ```

2. Settings → Devices & Services → Add Integration → "Sensus Analytics" —
   enter the portal base URL (`https://my-slc.sensus-analytics.com`),
   username/password, account number, meter number, and the values in
   "Recommended SLC configuration" above. The form validates the login
   before creating the entry.

## Running the tests

`homeassistant` 2026.x requires **Python ≥ 3.14.2** (domus runs 3.14.6), so
an older interpreter can't even install it. From the repo root, with a
throwaway venv *outside* the repo:

```
python3.14 -m venv /tmp/ha-venv
/tmp/ha-venv/bin/pip install homeassistant==2026.7.2 pytest
/tmp/ha-venv/bin/python -m pytest custom_components/sensus_analytics/tests -q
```

`test_api.py` and `test_translations.py` need no `homeassistant` and also
run under `rmp/.venv` (using the `--import-mode=importlib --rootdir=...`
form documented in `test_api.py`'s docstring). `test_sensor.py` and
`test_config_flow.py` genuinely need the real package — a prior note
claimed it was "installed in this dev environment", but no such
environment survived, which is why this recipe is recorded here.
