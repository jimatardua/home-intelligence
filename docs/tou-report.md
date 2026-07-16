# RMP Standard vs. Time-of-Use cost report

A cron-generated static HTML report (`energy_report/`) that answers a
concrete financial question: is it worth switching from RMP's standard
tiered rate to their opt-in Time-of-Use (TOU) rider, given our actual usage?

## Why this exists

The [RMP integration](rmp-integration.md) and the Daily Energy Story
dashboard give real hourly usage, A/C runtime, and EV charging data in Home
Assistant -- but the actual decision this data needs to support ("should we
switch rate plans?") is a financial one with real assumptions and caveats
that deserve to be shown, not a live dashboard tile. HA is the data
collection layer only; this report is generated separately, the same way
`~/Developer/infrastructure` generates its speedtest/bandwidth dashboards:
a self-contained stdlib Python script reads the data, renders a static
Chart.js HTML page, cron regenerates it every 2 hours, nginx serves it.

## Confirmed tariff data (RMP Schedule 1, Utah, effective Dec 1, 2025)

Read directly from RMP's PSC-filed tariff PDFs, not a secondhand summary.
Both plans share a $12.00/month customer charge (single-family,
single-phase).

**Standard (current) plan** -- tiered, billed per calendar month:
- Jun-Sep: 9.3199 cents/kWh first 400 kWh, 12.0130 cents/kWh above 400
- Oct-May: 8.2477 cents/kWh first 400 kWh, 10.6309 cents/kWh above 400

**TOU option** (opt-in rider, same schedule) -- no usage tiers, pure per-hour
on/off-peak classification:
- On-peak: 6:00pm-10:00pm, Mon-Fri, excluding 8 named holidays (with
  Friday/Monday observance shift for a holiday landing on a weekend)
- Off-peak: everything else
- Jun-Sep: 32.0834 cents/kWh on-peak, 7.1296 cents/kWh off-peak
- Oct-May: 28.3924 cents/kWh on-peak, 6.3094 cents/kWh off-peak
- RMP guarantees TOU won't cost more than 10% more than standard billing in
  the first 12 months (credited back) -- a real risk cap, footnoted in the
  report rather than simulated.

RMP's own EV-specific TOU pilot (Schedule 2E) is a dead end: closed to new
enrollment since April 2025, and its terms auto-migrated existing enrollees
to this same Schedule 1 TOU rider on Dec 1, 2025. Only these two plans
exist to compare.

**Tariffs are versioned, not static.** The energy-charge sheet actually read
is itself a "Second Revision... Canceling First Revision" -- RMP has already
revised these exact rates once and will again. `tariffs.py` holds a dated
registry (`TARIFF_VERSIONS`, each entry with its own `effective_start`), and
every billing calculation looks up whichever version was actually in effect
for the hour being billed via `tariff_for_date()` -- never "whatever's
current." A future rate change is a new registry entry, not a rewrite that
would silently reprice historical data.

A/C estimated draw when running: **~5.8 kW**, from the Lennox XC14-060
condenser's own nameplate (compressor RLA 26.4A + fan FLA 1.8A = 28.2A at
230V x ~0.9 assumed power factor) -- a deliberate choice over statistical
estimation from usage spikes.

## Design decisions

**Three tiers of claim, not one blended number** -- honest at any data
volume:
1. **Observed** -- cost for the exact hours of data collected so far under
   both plans, zero scaling. Always true regardless of data volume.
2. **Projection** -- daily-average scaled to month/year, only for a season
   actually observed. Explicitly shows "insufficient winter data" rather
   than applying winter rates to a summer usage pattern.
3. **Data maturity badge** -- `<14 days` = insufficient, `14-60 days` =
   early/single-season signal, `60+ days spanning both seasons` = real
   seasonal comparison. Same script, stronger output as data accumulates.

**Sensitivity table, not one number** -- a set of independent, named
"what if I changed X" levers (`sensitivity.py`), each recomputing TOU cost
holding everything else at its actually-observed value, so rows are
independently interpretable rather than additive:
- Delay each car's EV charging to off-peak (per car) -- best-case/upper-
  bound; doesn't validate the car is actually home during the hypothetical
  off-peak window. Reports "no on-peak charging observed yet" for a car
  rather than a misleading "+$0."
- Reduce on-peak A/C runtime by 10% -- reprices the nameplate-based A/C
  estimate as if on-peak runtime were cut by that percentage.
- Two **pending** levers -- "dishwasher after 10pm" and "shift dryer" --
  listed but unimplemented, since neither appliance has any monitoring
  today (no smart plugs, no circuit-level data). Tied to the already-
  planned Emporia Vue whole-home monitor (`roadmap.md` Phase 3); adding a
  real lever later is one new function plus one registry entry.

**Load disaggregation is a residual, not three independently-measured
numbers**: `other/baseline = total - A/C - EV`. Neither A/C nor EV charging
is separately metered, so "other" absorbing any data-gap mis-attribution is
the conservative, correct behavior -- not a bug.

**Billing-month tiering** approximates with calendar-month boundaries
(`BILLING_CYCLE_START_DAY`), stated explicitly in the report rather than
buried.

**Cron sequencing** doesn't chase RMP's variable daily-poll time -- the
report is self-describing, using each archive file's own `fetched_at`
rather than wall-clock `now()`, the same defensive pattern the Daily Energy
Story dashboard already uses for its `-2d` span offset. Runs every 2 hours
(not once daily) precisely so it doesn't need to guess when RMP's own
coordinator actually refreshes the archive on a given day -- whichever run
happens after that day's real update picks it up within a couple hours,
rather than waiting up to 24.

## File layout

```
energy_report/
  tariffs.py          # TARIFF_VERSIONS registry, tariff_for_date(), season_for(),
                       # is_on_peak(), holiday observance-shift logic
  billing.py           # compute_schedule1_cost(), compute_tou_cost(), both
                       # tariff-version-aware; calendar-month grouping
  archive_loader.py     # reads rocky_mountain_power_archive/*.json, gap-aware,
                       # hour-ending -> hour-start conversion
  ha_recorder.py         # read-only sqlite3 access: states/states_meta join,
                       # UTC epoch -> America/Denver, binary_sensor on/off
                       # intervals, numeric sensor samples
  disaggregation.py      # A/C kWh (on-time x 5.8kW), EV kWh (step-held
                       # integration of charger power samples), other = residual
  sensitivity.py          # the lever framework + two implemented levers +
                       # two pending levers
  render.py                # HTML/Chart.js template, mirrors
                       # generate_local_bw_dashboard.py's conventions
  generate_report.py        # CLI entry point, ties it together, atomic write
  deploy.sh                  # rsync to domus; prints (doesn't run) the
                       # one-time cron/nginx/container steps below
  tests/                       # pytest, run via energy_report/.venv
```

Deployed as a proper Python package (relative imports throughout) rather
than a single self-contained script like the infrastructure project's
bandwidth dashboards -- this has genuine correctness requirements (holiday/
DST-observance shifting, tiered billing, hour-ending timestamp conversion,
gap handling) worth isolating and unit-testing per module. Still
stdlib-only in production; pytest is a dev-only dependency in a scoped
`energy_report/.venv/`.

## Setup

1. `energy_report/deploy.sh` -- rsyncs the package to
   `domus:/opt/home-intelligence/energy_report/` and prints the remaining
   manual steps (it does not run them, since they touch a live, shared
   container and this machine's crontab).
2. Add a cron entry on domus running
   `python3 -m energy_report.generate_report` (module invocation, not a
   direct script path -- required because of the relative imports above)
   with `cwd=/opt/home-intelligence`, pointing `--archive-dir` and
   `--db-path` at the live archive/recorder DB, `--output` at
   `energy_report/output/index.html`.
3. Add an `/energy-report/` `location` block to
   `/etc/nginx-ha-proxy/default.conf`, above the existing catch-all
   `location /`.
4. Recreate (stop/rm/re-run, not just restart) the `ha-proxy` container with
   one additional bind mount for the report's output directory -- Docker
   can't add a mount to a running container, and there's no compose file
   managing this bare `docker run`.

## Known risks / things to watch

- **A/C and EV charging are estimated, not separately metered.** A/C uses a
  nameplate-derived constant draw, not measured power -- real compressor
  draw varies with outdoor temperature and duty cycle. EV charging is
  zero-order-hold integration of sparse instantaneous power samples, not a
  continuous reading.
- **EV charger sensors are mostly `unknown`/`unavailable` today**, with only
  occasional real readings -- the report explicitly shows "no on-peak
  charging observed yet" rather than a misleading `$0` savings for a lever
  it can't actually compute.
- **Every sensitivity lever is a best-case/upper-bound re-pricing of
  already-observed hours, not a simulation of new behavior** -- shifting EV
  charging doesn't confirm the car will actually be plugged in and idle
  during the hypothetical off-peak window.
- **Billing-cycle start day is assumed, not confirmed** -- calendar-month
  boundaries are a stated approximation, not RMP's actual billing cycle.
- **Winter projections are deliberately withheld until winter data exists**
  -- there is currently no mechanism to validate a winter-rate projection
  built from summer usage patterns, and showing one anyway would be a
  confident-looking number built on an unverified assumption.

## Status

- [x] `tariffs.py`
- [x] `billing.py`
- [x] `archive_loader.py`
- [x] `ha_recorder.py`
- [x] `disaggregation.py`
- [x] `sensitivity.py`
- [x] `render.py`
- [x] `generate_report.py`
- [x] Unit tests (52 passing) across all six logic modules, including a
      tariff-version boundary lookup, holiday weekend-observance shifting
      (including a cross-year-boundary case), a DST transition date, the
      cross-hour-boundary EV step-hold bug found and fixed during
      development, and independence between sensitivity levers
- [x] `deploy.sh`
- [ ] Deployed to domus and verified end-to-end (cron entry live, nginx
      location block added, `ha-proxy` container recreated with the new
      bind mount, `curl` against the real URL confirmed)

## Phase 2 (deferred): AI narrative layer

Once Phase 1 ships and the numbers are trusted, an optional layer calls the
self-hosted Ardua AI platform (`~/Developer/ardua-ai`) to narrate the
already-computed numbers -- a new `energy-advisor` Advisor, registered as
its own app with its own API key. Per that project's own governing
principle (`docs/ardua-ai-integration/ai-001-daily-ai-insight-card.md`):
**the AI explains, it does not calculate.** The report generator would build
a compact structured JSON summary (totals, cost comparison, disaggregation
breakdown) and POST it to `/v1/advisor/energy-advisor/chat`, embedding the
returned narrative at the top of the HTML report. Registering a new app
means editing the ansible vault and redeploying the shared ai-api stack --
that redeploy needs explicit confirmation immediately before running it,
not just because the vault password file happens to be available locally.
