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

Jim's meter was recently upgraded to digital; his wife Irina holds the
actual portal login, so live deployment is currently **blocked** — see the
last section.

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
- **`manifest.json` / `strings.json`** — standard HA integration metadata
  and config-flow field labels/error strings.
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
   that `is_matching` is gone). 40 tests, all passing.
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

## Deferred (not done here, flagged for later)

- **Splitting billing/tariff config out of the credentials schema.** The
  config flow still mixes API credentials with billing-tier pricing
  fields in one flat schema, matching upstream. Splitting those (mirroring
  `energy_report`'s `billing.py`/`tariffs.py` separation elsewhere in this
  repo) is a real possible improvement but wasn't part of the actual ask.
- **Confirming `UPDATE_INTERVAL` against SLC's real cadence.** 30 minutes
  is a documented, conservative guess — can't be confirmed without live
  credentials. Tune once real update timestamps have been observed against
  `my-slc.sensus-analytics.com`.
- **Upstream issue #85** (historical backfill on first setup) — not needed
  for this use case.

## Setup

1. Deploy `custom_components/sensus_analytics/` to
   `domus:/var/lib/homeassistant/homeassistant/custom_components/`, then
   `ha core restart`.
2. Settings → Devices & Services → Add Integration → "Sensus Analytics" —
   enter the portal base URL (`https://my-slc.sensus-analytics.com`),
   username/password, account number, meter number, and billing-tier
   pricing.

## Blocked on Irina's credentials

Everything above (fork, patches, all 40 tests, docs) is done and needs no
live credentials to verify. What's still outstanding, and can't proceed
without Irina's SLC Sensus Analytics username, password, account number,
and meter number:

- Actually deploying to `domus` and adding the integration through HA's
  UI.
- Confirming login succeeds and real sensor values populate, matching what
  the `my-slc.sensus-analytics.com` web portal shows.
- Observing the real update cadence over a day or two and tuning
  `UPDATE_INTERVAL` in `const.py` if 30 minutes turns out wrong for SLC's
  instance specifically.
