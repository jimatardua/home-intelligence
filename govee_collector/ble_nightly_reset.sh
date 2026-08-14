#!/usr/bin/env bash
# Preemptive nightly BLE adapter bounce for mrteeny's govee_collector.
#
# hci0 has wedged into a silent org.bluez.Error.InProgress state twice now
# (2026-08-10, 2026-08-14), both times with no contending process --
# BlueZ itself appears to periodically get stuck independent of anything
# this project controls. collector.py's own watchdog detects and retries
# this, but once retries are exhausted (the "stuck" health status) it just
# waits for a human -- see docs/govee-cigar-monitor.md's "Known risks"
# section. This script runs the same reset sequence that fixed it both
# times, on a schedule, so the adapter ideally never reaches that state at
# all rather than waiting to detect and recover from it after the fact.
#
# Scheduled via cron at 4am America/Denver (see deploy.sh) -- a brief
# (~10-20s) gap in cigar-storage monitoring at that hour is an acceptable
# tradeoff against needing a manual SSH-in every few days.
set -uo pipefail

log() { echo "$(date -Is) $*"; }

log "Starting nightly BLE adapter reset"
sudo hciconfig hci0 down
sudo hciconfig hci0 up
sudo systemctl restart bluetooth
sleep 5
sudo systemctl restart govee-collector
log "Nightly BLE adapter reset complete"
