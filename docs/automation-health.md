# Automation health: weather-upload backoff + Prometheus error metric

Two related fixes for the same incident: on 2026-08-20/21, every outbound
HTTPS call from the `homeassistant` container failed for ~10 hours
(17:40 UTC -> 03:20+ UTC) -- Weathercloud, Weather Underground, PWSWeather,
Tesla Fleet, NWS forecast, all of it. Root-caused by a parallel Claude
session ("infrastructure-24," working the network side) to the internal
Docker/hassio bridge between the `homeassistant` container and its own DNS
container (`hassio_dns`) -- the router, shared LAN/ISP, domus's host
networking, and `hassio_dns` itself were all individually confirmed healthy
the entire window. It self-healed without a restart; there's no code fix for
the outage itself. See that session's findings (relayed in this project's
own session transcript) for the full elimination trail.

That incident exposed two real gaps, not the root cause but worth fixing on
their own:

1. It was only discovered ~10 hours late, via Weathercloud's own "device
   offline" email -- no proactive alerting from this side at all.
2. The two weather-upload automations retried every 5-10 minutes for the
   entire 10 hours with zero backoff, silently spamming identical errors.

## Part 1: backoff (live HA config, not in this repo)

`automations.yaml` and `configuration.yaml` on domus
(`/var/lib/homeassistant/homeassistant/`) -- edited directly via the same
scp-pull/edit/scp-push pattern used for nginx config earlier this project,
with a timestamped backup made first.

Two automations changed: `weathercloud_upload` (10-min trigger) and
`wunderground_pwsweather_upload` (5-min trigger, covers both WU and
PWSWeather -- they share one trigger and, in practice, fail together).

**No try/catch needed.** A failed `rest_command` call aborts the rest of
that automation's action sequence -- confirmed directly in the incident's
own logs ("Error while executing automation" is always the terminal line,
nothing after it ever ran). So the mechanism is:

- One `input_datetime` helper per automation
  (`weathercloud_last_success`, `wu_pwsweather_last_success`), declared
  inline in `configuration.yaml` (matching how `zone:`/`template:` are
  already declared there rather than a new `!include` file for two
  helpers).
- A template condition on each automation, alongside the existing
  sensor-validity check, implementing a 3-tier backoff based on minutes
  since that automation's own last recorded success:
  - < 60 min: attempt every trigger tick (today's behavior, unchanged --
    a real transient blip still recovers fast)
  - 60-360 min: attempt only at :00/:30 (throttled to every 30 min)
  - 360+ min: attempt only at :00 (throttled to hourly)
  - helper never set (fresh deploy): treated as 0 minutes, always attempt --
    so the new helpers don't block real functionality before their first
    success
- A final action step on each automation -- `input_datetime.set_datetime`
  to now() -- which, per the abort-on-failure behavior above, only ever
  runs when every preceding call in that automation actually succeeded.

Deployed via `POST /api/services/input_datetime/reload` and
`POST /api/services/automation/reload` -- no HA restart needed.

## Part 2: Prometheus error-count exporter (`automation_health/`)

New git-tracked package, matching this repo's cron-driven one-shot pattern
(`home_dashboard`/`cigar_dashboard` style, not `govee_collector`'s
persistent-daemon style -- nothing here needs to stay running between
runs).

**Real finding that changed the design**: HA's own `/api/error_log` REST
endpoint 404s on this install -- not usable. `docker logs homeassistant
--since <window>` works without sudo (jramsey is in the `docker` group) and
produces exactly the timestamped, leveled lines needed, so that's the
actual data source. This means the package needs **no HA token at all** --
one less secret to manage compared to `control_panel`.

**Second real finding**: `/var/lib/node_exporter/textfile_collector/` is
owned by `node_exporter:node_exporter`, not jramsey -- a direct write is
`Permission denied` (confirmed live). jramsey already has passwordless sudo
for everything on domus (pre-existing, not something this package grants),
used narrowly here via `sudo install -o node_exporter -g node_exporter -m
644` to place one file -- `install` copies and atomically renames in one
step, matching node_exporter's documented safe-write contract, without
touching the directory's own ownership.

**Also surfaced in passing, not fixed here**: the WU/PWSWeather
`rest_command` logs its full request URL on every error, including the
account password in plaintext, visible to anyone with `docker logs` access.
Pre-existing, unrelated to the outage. `log_parser.py` is deliberately built
to never capture or return a log line's message body -- only
`(timestamp, level, logger)` -- specifically so this package can never leak
that password (or anything else embedded in a future error message) into
the `.prom` file, `cron.log`, or anywhere else it touches.

### Counting model

A single failed automation run logs ERROR lines on **two different
loggers**: the generic `homeassistant.components.rest_command` (once, "Error
fetching data") and the automation's own
`homeassistant.components.automation.<id>` (twice -- "Error executing
script" and "Error while executing automation"). Rather than trying to
deduplicate these into one "number of failures" count (which would need
inferring which rest_command line belongs to which automation, easy to get
wrong), each logger is counted independently as its own metric label:

```
# HELP home_intelligence_automation_upload_errors Count of ERROR-level Home Assistant log lines in the lookback window (docker logs homeassistant), per logger -- NOT deduplicated per failed run.
# TYPE home_intelligence_automation_upload_errors gauge
home_intelligence_automation_upload_errors{automation="weathercloud_upload"} 0
home_intelligence_automation_upload_errors{automation="wu_pwsweather_upload"} 0
home_intelligence_automation_upload_errors{automation="rest_command"} 0
```

All three labels are always emitted, including zeros, so a healthy window
reads as "0 errors" rather than "no data" in Grafana. `rest_command` counts
*any* `homeassistant.components.rest_command` ERROR, not just the two
watched automations' -- it's a genuinely different, useful signal (catches
future/unwatched rest_commands too), not an "other" bucket meant to be
mutually exclusive with the watched-automation counts.

**Staleness metric, added after the infrastructure session wired up the
Grafana alert**: a count-only metric reads as "0 errors, all healthy" if
the collector itself silently stops running (cron dies, `docker logs`
keeps failing, etc.) -- identical to genuinely healthy from Prometheus's
point of view. `home_intelligence_automation_upload_collection_timestamp_seconds`
is a unix timestamp, updated only on a fully successful collection (fetch +
parse + write all succeeded), so staleness can be alerted on independently
of the error counts. Same failure shape the infra session had separately
hit with a speedtest metric that week.

### Architecture

```
automation_health/
  const.py       -- watched-automation logger fragments -> labels,
                     textfile-collector path/ownership, lookback default
  docker_log.py  -- `docker logs homeassistant --since <N>m`, ANSI-stripped
  log_parser.py  -- parses (timestamp, level, logger) only, never the
                     message body; buckets ERROR lines within the lookback
                     window by logger
  exporter.py    -- Prometheus text rendering + the sudo-install write
  collect.py     -- CLI entry point (python3 -m automation_health.collect),
                     cron'd every 10 minutes
  deploy.sh
```

On a `docker logs` failure, `collect.py` deliberately leaves the previous
`.prom` file untouched rather than writing a "0 errors" metric that would
read as healthy when the check itself just couldn't run -- node_exporter
serves slightly-stale data instead of a false "all clear."

### Verification

- 32 tests (`automation_health/tests/`) -- `log_parser.py` tested against
  real captured log lines from the actual incident (exact format, ANSI
  codes included in the docker_log tests specifically, since that's the
  layer responsible for stripping them), including an explicit test that a
  line with the real embedded password never surfaces in a parsed
  `LogEntry`; `exporter.py` tested for correct Prometheus text and the
  exact `sudo install` invocation (subprocess mocked); `collect.py` tested
  for correct wiring, for leaving the previous file (and `last_collected_at`)
  untouched on failure, for falling back to the default lookback on a
  first-ever run, and for computing the delta window correctly on
  subsequent runs.
- Deployed and run once by hand on domus, confirmed the `.prom` file
  appears with correct ownership and content.
- Sanity-checked the parser against the actual saved incident log excerpt
  from this session's own investigation -- correctly attributed
  weathercloud's errors; the WU/PWSWeather count came back 0 against that
  particular excerpt because the original ad hoc `grep` used to
  investigate the incident (filtered on literal substrings like
  `weathercloud`/`rest_command`) happened to miss WU/PWSWeather's own
  automation-logger lines entirely -- a gap in that old investigation grep,
  not in this parser, which doesn't filter by keyword at all and is
  confirmed correct by the dedicated unit tests instead.

## Flapping alert (2026-08-21/22)

Once the Grafana alert (`>0 sustained for 10m`) was live, it paged
repeatedly overnight -- both on `domus` and on `popcorn` (confirmed to be
the same physical machine under two separate Prometheus scrape labels, so
every real event was being counted, and paged, twice).

**Not a repeat of the original outage.** Pulling the actual `docker logs`
for the affected day showed 8 separate, brief, isolated blips -- one
failed automation attempt, resolved by the very next retry 5 minutes
later -- roughly every 1-3 hours, all day, every single one hitting only
`wu_and_pwsweather` (never `weathercloud`). Most likely ongoing low-grade
DNS flakiness specifically resolving `wunderground.com`/`pwsweather.com`,
possibly the tail of the same Docker/hassio bridge issue from the original
incident, now showing as brief blips instead of a sustained outage rather
than something new.

**Why it paged anyway**: the exporter's original design used a 30-minute
*sliding* lookback window -- every collection run counted "errors in the
last 30 minutes," re-counting the same event on every run until it aged
out. A single 5-minute blip stayed visible in the metric for up to 30
minutes afterward, comfortably longer than Grafana's 10-minute sustained
threshold -- so every one of those 8 harmless, self-recovering blips
triggered a full WARNING -> Resolved page cycle. The alert was working
exactly as configured; the metric it was reading was the problem. A
boolean `>0` threshold can't tell "one blip" from "a real systemic
outage" on its own -- only magnitude or a properly-scoped window can.

**Fix**: `collect.py` now counts errors *since the last successful
collection* -- a disjoint delta window, not a sliding one -- persisted via
a small state file (`automation_health/collector_state.json`, gitignored,
runtime state not config). A single isolated blip is now visible in only
the one reading that actually covers it, for at most one collection
interval, well under any reasonable sustained-alert threshold; a
genuinely ongoing problem still shows up in every consecutive reading,
since new errors keep landing inside each new window as they happen --
detection latency for a real incident is actually *better* than before,
not worse. Cron cadence tightened from 10 to 5 minutes to match
`wu_pwsweather_upload`'s own trigger interval (the tightest of the two
watched automations), so the collection window is never wider than
necessary to avoid missing a real occurrence.

Relayed to the infrastructure session as a two-part fix: the exporter
change above (this project's side, shipped immediately since the flapping
was actively disrupting sleep and infra wasn't reachable at the time) plus
a recommendation to also switch their Grafana alert condition from a
boolean `>0` to a count threshold (e.g. `>= 6 sustained for 10m`) as
defense in depth, backed by the real data above: isolated blips = 2-3 per
label per window, worst coincidental double-blip = 6, the original
10-hour outage would have produced 100+ per label per window. Also flagged
the domus/popcorn double-counting as worth deduping at the scrape-config
level, separately from the alerting-logic fix.

**Resolution, confirmed by infra (commit `b2a0c23`)**:
- Grafana alert switched to `count >= 6 sustained 10m`, deployed.
- `popcorn` was a real bug on their side, not just a labeling quirk --
  domus's pre-rename hostname, deliberately kept alive in DNS ("legacy
  name," intentional), but it also still had its own standalone
  Prometheus scrape target left over from before the rename that was
  never cleaned up. Every metric and every alert had been silently
  double-counted/double-paged since whenever that stale target was added
  -- not specific to this metric. Duplicate target removed.
- The DNS-flakiness lead got a real, narrower answer, not just a
  reproduction of the original finding: infra checked pfSense's Unbound
  resolver log and `hassio_dns`'s own logs at the exact blip timestamps --
  both clean, and critically, the DNS query *never reaches `hassio_dns`
  at all* during a blip. So it's confirmed to be inside the Docker/hassio
  bridge path specifically (same general area the original 10-hour outage
  was narrowed to), not a DNS server problem, not upstream of the Pi --
  just intermittent now instead of sustained. Not pursued further from
  the infra side (kernel/iptables/conntrack territory, outside what's
  efficient to investigate from there) -- left here as a real, specific
  lead if this ever becomes worth chasing down properly, rather than
  something actively being worked.

## Not in scope

- **`automation.upload_eve_weather_readings_to_weather_underground`** --
  an orphaned entity (state `unavailable`, no backing automation left in
  `automations.yaml`) likely left over from before Weather Underground got
  merged into the combined `wunderground_pwsweather_upload` automation.
  Not cleaned up here; flagged to Jim only in passing.
- **The WU/PWSWeather plaintext-password-in-logs issue** described above --
  worth fixing on HA's side at some point, but a separate concern from
  either the outage or these two fixes.
- **The intermittent Docker/hassio bridge DNS issue** (see "Flapping
  alert" -> "Resolution" above) -- confirmed real and specifically
  localized (query never reaches `hassio_dns`), but not pursued further;
  kernel/iptables/conntrack-level investigation, worth prioritizing only
  if it starts happening more often or for longer.
