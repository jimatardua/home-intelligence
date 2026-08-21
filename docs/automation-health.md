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

- 23 tests (`automation_health/tests/`) -- `log_parser.py` tested against
  real captured log lines from the actual incident (exact format, ANSI
  codes included in the docker_log tests specifically, since that's the
  layer responsible for stripping them), including an explicit test that a
  line with the real embedded password never surfaces in a parsed
  `LogEntry`; `exporter.py` tested for correct Prometheus text and the
  exact `sudo install` invocation (subprocess mocked); `collect.py` tested
  for correct wiring and for leaving the previous file alone on failure.
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

## Not in scope

- **`automation.upload_eve_weather_readings_to_weather_underground`** --
  an orphaned entity (state `unavailable`, no backing automation left in
  `automations.yaml`) likely left over from before Weather Underground got
  merged into the combined `wunderground_pwsweather_upload` automation.
  Not cleaned up here; flagged to Jim only in passing.
- **The WU/PWSWeather plaintext-password-in-logs issue** described above --
  worth fixing on HA's side at some point, but a separate concern from
  either the outage or these two fixes.
- **Grafana alert rule** -- explicitly the infrastructure session's side,
  once this metric exists and is confirmed live.
