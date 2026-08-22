#!/usr/bin/env bash
# Deploys the automation_health package to domus and prints (does not
# execute) the remaining one-time manual step -- the cron entry -- since it
# touches this host's crontab, meant to be reviewed and run deliberately.
#
# Usage: automation_health/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/automation_health"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing automation_health/ to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'tests' \
  --exclude 'cron.log' \
  --exclude 'collector_state.json' \
  --exclude 'deploy.sh' \
  "${SCRIPT_DIR}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Sync complete."
echo
echo "The following step is NOT run automatically -- it touches this"
echo "host's crontab. Review and run it deliberately:"
echo
cat <<'EOF'
--- 1. Cron entry (crontab -e on domus) --------------------------------------

*/5 * * * * cd /opt/home-intelligence && /usr/bin/python3 -m automation_health.collect >> /opt/home-intelligence/automation_health/cron.log 2>&1

5 minutes matches wu_pwsweather_upload's own trigger interval (the
tightest of the two watched automations) -- each collection window is a
disjoint delta since the last successful run, not a sliding lookback (see
collect.py's docstring and docs/automation-health.md's "Flapping alert"
section), so the cadence needs to be tight enough that every real
occurrence lands in its own reading. No env file, no systemd unit -- the
data source is `docker logs homeassistant` (jramsey is already in the
docker group), not the HA REST API, and the textfile write goes through
jramsey's existing passwordless sudo (see exporter.py) rather than a new
credential.

--- 2. Verify ------------------------------------------------------------------

    python3 -m automation_health.collect  # run once by hand first
    cat /var/lib/node_exporter/textfile_collector/automation_health.prom
    tail -f /opt/home-intelligence/automation_health/cron.log
EOF
