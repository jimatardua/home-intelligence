# Rocky Mountain Power custom integration

A custom Home Assistant integration (`custom_components/rocky_mountain_power/`)
that pulls hourly electricity usage directly from Rocky Mountain Power's
customer portal (`csapps.rockymountainpower.net`) and feeds it into HA's
Energy Dashboard.

## Why this exists

RMP/PacifiCorp has no official HA integration and isn't in HA's
Opower-supported utility list. The only community option
(`jaredhobbs/rocky-mountain-power`) drives a headless browser (Selenium)
against the same portal and requires disabling account MFA to work — a real
security trade-off, plus it's fragile (has broken before per its own commit
history) and adds real overhead on a Raspberry Pi.

Instead, this integration talks to RMP's backend directly over HTTP,
replicating what their own Angular app does — no browser, no MFA trade-off.

## How RMP's portal actually works

It's a Spring Boot backend + Angular SPA, not Opower under the hood. Getting
usage data requires replicating two independent layers:

### 1. Login (Azure AD B2C)

Standard "self-asserted" custom-policy flow: tenant `bheb2c.onmicrosoft.com`,
policy `B2C_1A_PAC_signin`, client_id `787c4bc2-e588-4ae3-a07e-146670158f87`.

1. `GET /oauth2/authorization/B2C_1A_PAC_SIGNIN` (follow redirects) → lands on
   B2C's hosted login page, which embeds a `var SETTINGS = {"csrf": "...",
   "transId": "StateProperties=..."}` blob.
2. `POST .../B2C_1A_PAC_signin/SelfAsserted?tx=<transId>&p=B2C_1A_PAC_signin`,
   header `X-CSRF-TOKEN: <csrf>`, form body
   `request_type=RESPONSE&signInName=<username>&password=<password>`.
3. `GET .../B2C_1A_PAC_signin/api/CombinedSigninAndSignup/confirmed?...` →
   redirect chain carrying an OAuth `code`.
4. `GET /login/oauth2/code/?state=...&code=...` → Spring backend exchanges
   the code and establishes a session cookie.

### 2. Request-body encryption

The session cookie alone isn't enough — every mutating API call also needs a
client-side-encrypted body, independent of the login above. This was reverse
engineered from the site's own JS bundles and confirmed live end-to-end:

- Generate two RSA-4096/SHA-256 keypairs: one for signing
  (`RSASSA-PKCS1-v1_5`), one for key exchange (`RSA-OAEP`).
- `POST /idm/handshake` with both public keys (SPKI, base64, joined with
  `:`). The server responds with an AES-256 key, RSA-OAEP-encrypted under
  the client's own OAEP public key.
- Per request: sign the plaintext JSON body (PKCS1v15/SHA-256) with the
  signing private key → base64 → `X-WCSSS-Content-Signature` header.
  AES-256-GCM encrypt the same plaintext with a random 12-byte IV, tag
  length 128 → body becomes `base64(iv) + base64(ciphertext+tag)`.
- Responses come back as plain JSON — only requests are encrypted.
- Every mutating request also needs `X-XSRF-TOKEN` (Angular's default
  double-submit CSRF header, read from the `XSRF-TOKEN` cookie), or the
  backend silently serves the SPA's HTML shell instead of a real API
  response — the standard symptom of a missing/expired session.

Both layers are established together at login and treated as one unit — see
"Session lifecycle" below.

### 3. Account resolution → usage data

Once authenticated, getting a day's hourly readings requires resolving
account identifiers first:

```
getAccountList          -> customerIDN, accountSequence
getMeteredAgreements    -> siteIDN, serviceSequence, agreementSequence
getIntervalUsageForDate -> hourly {readDate, readTime, usage} readings
```

`registerType` (required by `getIntervalUsageForDate`) isn't returned by any
account-resolution call — it's a fixed `"01"` for single-register
residential AMI meters, confirmed against the live API.

Reading times are **hour-ending**, not hour-starting: a reading with
`readTime: "03:00"` covers 02:00–03:00, and `readTime: "24:00"` covers
23:00–24:00 of the *same* `readDate` (it does not roll into the next day).

## Why external statistics, not a live-polled sensor

RMP's interval data lags about a day (fetching "today" returns yesterday's
hourly readings). A regular HA sensor entity's long-term statistics are built
from *when the entity's state changes in real time* — they can't represent
"this was the usage from 3–4pm yesterday." This is exactly the problem the
official `opower` integration solves by using
`homeassistant.components.recorder.statistics.async_add_external_statistics`
to inject correctly-backdated hourly sums under a synthetic statistic_id
(`rocky_mountain_power:energy_consumption`, not tied to any live entity).
This integration follows the same pattern — it's the only mechanism that
represents backdated hourly data correctly, and it's what makes the data
selectable in the Energy Dashboard's "Grid consumption" picker.

Because a day's readings can arrive or get corrected up to a few days late,
the coordinator re-pulls and re-imports a trailing window of days on every
poll rather than just "yesterday." External statistics imports are
idempotent per hour (`start` timestamp), so re-importing already-seen hours
safely overwrites rather than duplicates.

## Raw archive, independent of HA's statistics

Per this project's own principle that historical data should never be
discarded unnecessarily, and that HA owns collection while Ardua AI
eventually owns analysis, HA's recorder database is not the only copy of
this data:

```
RMP API
   │
   ▼
Raw JSON archive (one file per day)
   │
   ├── Home Assistant statistics (via async_add_external_statistics)
   └── Ardua AI analytics (future, Phase 5 — reads the archive directly)
```

- Path: `/config/rocky_mountain_power_archive/YYYY-MM-DD.json` on domus —
  inside HA's own config dir, so it rides along with the existing NFS
  backup pipeline (nas44t, encrypted, 7 retained) rather than needing new
  backup infrastructure.
- Each file holds the day's readings essentially as returned by the API
  (`readDate`/`readTime`/`usage`), with no unit conversion or
  restructuring — the most defensive choice if a normalization bug is ever
  found later, and it's what lets HA's imported statistics be checked
  against the original utility data during future debugging.
- Written before the statistics-import step, so the archive still succeeds
  even if statistics import fails for some reason.

## File layout

- **`const.py`** — endpoints, B2C/tenant constants, crypto parameters
  (RSA key size, hash algorithm, header names), polling/lookback intervals.
- **`api.py`** — `RockyMountainPowerClient`. **Deliberately synchronous**
  (uses `requests`, not `aiohttp`) — see "Known risks" below for why; it
  owns a private `requests.Session` (never HA's shared session, so this
  integration's cookies never mix with others'). `coordinator.py` and
  `config_flow.py` dispatch its methods via `hass.async_add_executor_job`,
  the standard HA pattern for wrapping a non-async library. Auth and the
  crypto handshake are encapsulated behind a single gate:
  - `ensure_authenticated()` — every public method calls this first. It's a
    no-op if the session is still fresh; otherwise it re-logs-in (and
    re-runs the crypto handshake) transparently. Callers never reason about
    session state themselves.
  - `_login()` — the B2C flow above, plus the handshake, plus a best-effort
    fetch of the frontend bundle signature (see `site_bundle_signature`
    below) from the app's own shell page — not the B2C login page, which is
    Microsoft's Identity Experience Framework UI and references none of
    RMP's own JS.
  - `parse_settings(html)` — standalone function isolating the `SETTINGS`
    blob extraction, so a future RMP page-markup change only needs a fix in
    one named place.
  - `get_metered_agreements(force_refresh=False)` — resolves and **caches**
    account/meter identifiers; only re-fetched on demand.
  - `get_interval_usage(date)` — returns that day's hourly readings.
  - Distinct `CannotConnect` / `InvalidAuth` / `UnexpectedResponse`
    exceptions. A response that doesn't parse as JSON (the SPA-shell
    symptom) is treated as a sign the session/XSRF token died: it invalidates
    the session so the *next* call re-authenticates, rather than retrying
    inline.
  - Verbose debug logging throughout the login/handshake/request flow.
- **`coordinator.py`** — `DataUpdateCoordinator` subclass. Polls once daily
  (RMP's lag makes anything faster pointless), re-pulls a trailing window
  of days per run, writes the raw archive, then imports hourly statistics.
  Tracks `last_successful_sync`, `last_poll_duration_seconds`, and
  `latest_interval_date` for diagnostics to read.
- **`config_flow.py`** — single-step username/password form. Validates the
  credentials with a real login + account-resolution call before creating
  the config entry.
- **`__init__.py`** — standard `async_setup_entry` / `async_unload_entry`,
  creates the client + coordinator, stores them in `hass.data[DOMAIN]`.
- **`diagnostics.py`** — Settings → Devices & Services → Rocky Mountain
  Power → Download Diagnostics. Exposes: `authenticated`,
  `last_successful_sync`, agreement IDs (redacted), `latest_interval_date`,
  `last_poll_duration_seconds`, and `site_bundle_signature` — the hash
  fragment of RMP's frontend JS bundle captured at login (e.g.
  `main.c90d73ab362aa7afda39.js`). This doubles as an early-warning canary:
  if it changes between polls, RMP shipped a new frontend build, which is
  exactly the kind of change that could silently break `parse_settings()`
  or the request-encryption contract.
- **`manifest.json` / `strings.json`** — standard HA integration metadata
  and config-flow field labels/error strings.

## Setup

1. Deploy `custom_components/rocky_mountain_power/` to
   `domus:/var/lib/homeassistant/homeassistant/custom_components/`, then
   `ha core restart`.
2. Settings → Devices & Services → Add Integration → "Rocky Mountain
   Power" — enter your RMP username/password directly into HA's own form.
3. Once set up, the new statistic becomes selectable in Settings →
   Dashboards → Energy → "Grid consumption".

## Known risks / things to watch

- **This is unofficial and unsupported.** RMP can change their frontend,
  their auth flow, or the request-encryption scheme at any time without
  notice, which would break this integration until someone re-reverse-
  engineers the change. The `site_bundle_signature` diagnostic field is
  meant to give an early signal when that's happened.
- **RMP's WAF appears to fingerprint the TLS layer, not just request
  content.** `aiohttp` was rejected with a bare HTTP 400 at the SelfAsserted
  login step 100% of the time in testing, while `requests` succeeded 100%
  of the time, from the same machine/account, back to back, with the wire
  -level headers and body confirmed byte-identical against a neutral echo
  endpoint. (An initial theory that this was rate-limiting/anti-automation
  blocking from repeated attempts was ruled out the same way: `requests`
  kept succeeding immediately after `aiohttp` failed, from the same IP.)
  This is why `api.py` uses `requests` rather than HA's native `aiohttp` —
  if RMP's WAF posture changes, this may need revisiting.
- `registerType: "01"` is a confirmed-working value for this account's
  single-register residential meter, not something derived from any API
  response. Accounts with a different meter/register configuration (e.g.
  time-of-use, net metering with production) may need a different value.

## Status

- [x] Login flow + request-encryption handshake reverse-engineered and
      confirmed live (`rmp/poc_encrypted_client.py`)
- [x] `const.py`
- [x] `api.py`
- [x] `coordinator.py`
- [x] `config_flow.py`
- [x] `__init__.py`
- [x] `diagnostics.py`
- [x] `manifest.json` / `strings.json`
- [x] Deployed to domus and verified end-to-end — config flow validated a
      real login, the first coordinator run imported 53 hourly statistics
      into `rocky_mountain_power:energy_consumption` with a correctly
      ascending cumulative sum, raw archive files landed for all 3
      lookback days, the source is selectable in the Energy Dashboard, and
      a downloaded diagnostics dump confirmed every field (`authenticated`,
      `last_successful_sync`, `last_poll_duration_seconds`,
      `latest_interval_date`, `site_bundle_signature`, redacted
      `agreement_ids`) is populated correctly.
