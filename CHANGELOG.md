# Changelog

All notable changes to this project are documented here. Version is tracked
in the root `VERSION` file (this project has no single package manifest, so
`VERSION` is the canonical source of truth; the RMP HA integration's own
`manifest.json` version is independent, scoped to Home Assistant's own
per-integration update tracking).

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
