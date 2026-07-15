# Roadmap

## Phase 1

Infrastructure

- ~~Install Ubuntu LTS VM~~ — deployed as HA Supervised bare metal on a
  Raspberry Pi 4 (domus) running Debian 12 instead; see hardware.md
- Install Home Assistant — done, onboarding complete
- Configure backups — done: daily encrypted backups to nas44t
  (`/volume1/Backup/homeassistant`) via Supervisor's native NFS mount,
  retaining 7, plus a local copy on domus
- ~~Configure HTTPS~~ — deferred by design. HA stays HTTP on the internal
  LAN; if this is ever exposed externally, TLS terminates at the sideshowbob
  nginx reverse proxy, not on HA itself. If/when that proxy is added,
  configure HA's `http:` integration (`use_x_forwarded_for`,
  `trusted_proxies`) to trust it. Residual risk is LAN-local sniffing of
  credentials/session cookies, which is a network segmentation question
  (keep untrusted/IoT devices off the trusted LAN segment), not something
  HTTPS-on-HA would meaningfully fix here.
- Configure DNS — done: domus.ardua.lan resolves to 192.168.128.20

## Phase 2

Core integrations

- ~~Nest~~ / ~~Google Calendar~~ — done: both use one Google Cloud OAuth
  project/consent screen (`home-intelligence`), reusing the same Client
  ID/Secret. Real gotcha along the way: when the OAuth client was first
  created, the Client ID got misread off the screen and was one character
  short (`fik0nna2ik6` instead of the actual `fik0nnna2ik6`) — every
  "invalid_client" failure across ~40 minutes of retries was that typo, not
  Google's propagation delay it initially looked like. Fixed by re-reading
  the ID directly from the Google Cloud console and correcting it in both
  HA's stored application credentials and the Nest Device Access project.
  Lesson: when a newly-created ID/secret is read off a screen once and
  reused everywhere, re-verify it against the source before blaming
  external delay for a persistent auth failure.

  Nest device linking (separate from the above) needed its own detour:
  HA's Nest setup asks for two different project IDs that must NOT match
  (validated in `nest/config_flow.py`) — the actual Google Cloud project ID
  (`home-intelligence-502314`, used for Pub/Sub topic/subscription paths)
  and the Nest Device Access Console project ID (`732d4676-...`, used in
  the actual OAuth authorization URL). Mixing them up produces Google's
  generic "Something went wrong" error on the Nest authorization screen —
  confirmed against Google's own PCM error docs and HA's source, since
  the field labels alone don't disambiguate which ID goes where. Also:
  the Cloud Pub/Sub API must be manually enabled on the GCP project (easy
  to skip since Nest/HA doesn't use realtime events for anything we
  wanted — camera/doorbell — but the SDM integration requires a Pub/Sub
  topic + subscription regardless), and the Device Access project's
  Pub/Sub topic field must be enabled and pointed at the topic HA creates
  mid-flow before the config flow can finish.
- ~~Tesla (Jim)~~ / ~~Tesla (Irina)~~ — done: both vehicles turned out to be
  on one Tesla account, so a single Tesla Fleet integration covers both
  (Jim's Tesla + Irina's Tesla, both Model Y). Read-only scopes only
  (`vehicle_device_data`, `vehicle_location`), matching "observe only."
  Setup required: a Tesla Developer app (Fleet API, usage-based billing
  with a $10/mo personal-use credit), a public domain hosting a
  Tesla-generated EC public key at
  `https://www.ardua.com/.well-known/appspecific/com.tesla.3p.public-key.pem`
  (private key lives in HA's own config dir, `tesla_fleet.key`, covered by
  existing backups — Tesla never holds it), and the `my.home-assistant.io`
  redirect helper for OAuth. Command scopes intentionally deferred to
  Phase 4+ when automations are actually wanted.
- ~~Weather~~ — done: Met.no integration added. Caught along the way: HA
  onboarding's address entry didn't actually persist — core.config was
  still sitting at HA's Amsterdam default (lat/long) with elevation 0.
  Fixed via the location map (drag the home marker, not just click) and
  manually entering elevation in meters (UI wouldn't accept feet despite
  US customary units). Worth checking core.config on any fresh HA install
  before trusting anything location-based.

Goal:

Observe.

Do not automate yet.

---

## Phase 3

Energy

- ~~Rocky Mountain Power usage~~ — done: no first-party HA integration
  exists (verified live: not in HA's Opower-supported utility list), and
  the only community option (`jaredhobbs/rocky-mountain-power`) requires
  disabling account MFA and is a fragile Selenium scraper — rejected for
  both reasons. Instead, built a custom `custom_components/rocky_mountain_power/`
  integration that talks to RMP's backend directly over HTTP, reverse
  engineered from their own Angular SPA's JS bundles: an Azure AD B2C login
  flow, plus (unexpectedly) a full client-side request-encryption layer
  (RSA-4096 handshake + AES-GCM + request signing) that has nothing to do
  with the session cookie. Full writeup, architecture, and known risks are
  in `docs/rmp-integration.md`. Notable gotcha: HA's native `aiohttp` got
  silently rejected by RMP's WAF (bare HTTP 400, no detail) at the exact
  login step where `requests` succeeded reliably, byte-identical request
  confirmed via a neutral echo endpoint — pointed at TLS fingerprinting,
  not a logic bug, so the client is deliberately synchronous (`requests`,
  dispatched via `hass.async_add_executor_job`) rather than native asyncio.
  Verified end-to-end: real hourly statistics land in
  `rocky_mountain_power:energy_consumption`, selectable as an Energy
  Dashboard "Grid consumption" source, with a parallel raw-JSON archive on
  disk per architecture.md's "don't discard historical data" principle.
- Emporia Vue
- ~~Energy Dashboard~~ (partial, ahead of schedule) — built an "Energy &
  Comfort" HA dashboard using the two biggest known consumers we can
  already observe without Emporia Vue: HVAC and Tesla charging. Required
  two prerequisites worth remembering for any future dashboard work:
  (1) HA's default recorder purges raw history after only 10 days —
  changed to `purge_keep_days: 365` in configuration.yaml, since the
  default would have silently discarded exactly the granular data this
  dashboard needs. Long-term hourly statistics are unaffected either way
  (kept forever by default). (2) Installed HACS + the `apexcharts-card`
  community card for proper dual-line overlays (built-in History Graph
  can't do this well). Also added a small reusable template sensor,
  `binary_sensor.family_room_ac_running`, derived from the Nest
  thermostat's `hvac_action` attribute — this is the real "compressor is
  actively on" signal, distinct from just the thermostat's mode (cool/
  heat/off), which doesn't tell you whether it's actually running at any
  given moment. Dashboard has three cards: indoor vs outdoor temperature,
  AC-running vs vehicle-charging-status timeline, and vehicle charging
  power. Needs a couple of weeks of normal use (ideally spanning some hot
  afternoons) before the correlation view shows anything meaningful, since
  the underlying entities are brand new.
- ~~Daily Energy Story~~ — a second view on the "Energy & Comfort"
  dashboard: one apexcharts-card overlaying all six signals (whole-house
  power from RMP, indoor/outdoor temp, AC running, both cars' charging
  power) on a single shared time axis, so "was the spike from charging or
  HVAC" is a direct visual read instead of cross-referencing two separate
  cards. Both views converted from `masonry` to `panel` type so the charts
  use the full window width instead of a cramped multi-column layout.
  Hit a real, non-obvious HA recorder bug along the way: a statistic
  whose metadata has `has_sum=False` silently gets its `state` column
  dropped from every query, regardless of what's actually asked for or
  what's genuinely in the database — full story in
  `docs/rmp-integration.md`'s "Known risks" section. Chart currently
  defaults to two days back (`span: offset: -2d`) rather than "today" or
  "yesterday", since RMP's own reporting lag isn't fixed at exactly one
  day; expect to need to nudge that offset occasionally.

Goal:

Understand electrical consumption.

---

## Phase 4

Automations

- Window notifications
- HVAC recommendations
- EV charging reminders
- Shade scheduling

Goal:

Improve comfort while reducing cost.

---

## Phase 5

AI

Connect Ardua AI.

Capabilities:

- Daily home reports

- TOU optimization

- HVAC recommendations

- Explain unusual energy consumption

- Detect anomalies

- Long-term trend analysis

---

## Phase 6

Predictive optimization

Future possibilities

- Weather-aware HVAC scheduling

- Occupancy-aware automation

- Electricity cost optimization

- Vacation mode

- Predictive maintenance

- Natural-language interaction
