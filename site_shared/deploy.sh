#!/usr/bin/env bash
# Deploys the site_shared package to domus. Unlike every other deploy.sh in
# this repo, there is nothing to print after the sync: site_shared is pure
# Python source (theme/nav string-builders), imported as a sibling by the
# other three packages' render.py -- same pattern as home_dashboard/
# cigar_dashboard already importing energy_report.ha_recorder. No cron
# entry, no nginx location, no ha-proxy bind mount -- nothing here is ever
# served directly, so there's no infrastructure step for it.
#
# Usage: site_shared/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/site_shared"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing site_shared/ to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'tests' \
  --exclude 'deploy.sh' \
  "${SCRIPT_DIR}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Sync complete. No further steps -- site_shared has no cron entry,"
echo "    nginx location, or ha-proxy bind mount of its own."
