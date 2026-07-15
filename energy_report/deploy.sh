#!/usr/bin/env bash
# Deploys the energy_report package to domus and prints (does not execute)
# the remaining one-time manual steps -- crontab entry, nginx location
# block, and ha-proxy container recreation -- since those touch shared,
# currently-running infrastructure (HA's own reverse proxy) and are meant
# to be reviewed and run deliberately, not silently applied by this script.
#
# Usage: energy_report/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/energy_report"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing energy_report/ to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'tests' \
  --exclude 'output' \
  --exclude 'deploy.sh' \
  "${SCRIPT_DIR}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Sync complete."
echo
echo "The following steps are NOT run automatically -- they touch a live,"
echo "shared container (ha-proxy) and this machine's crontab. Review and"
echo "run them deliberately:"
echo
cat <<'EOF'
--- 1. Cron entry (crontab -e on domus) ---------------------------------

17 5 * * * cd /opt/home-intelligence && /usr/bin/python3 -m energy_report.generate_report --archive-dir /var/lib/homeassistant/homeassistant/rocky_mountain_power_archive --db-path /var/lib/homeassistant/homeassistant/home-assistant_v2.db --output /opt/home-intelligence/energy_report/output/index.html >> /opt/home-intelligence/energy_report/cron.log 2>&1

Note: this must run as `python3 -m energy_report.generate_report` with cwd
/opt/home-intelligence (not a direct script path) -- generate_report.py
uses relative imports (`from .archive_loader import ...`), so it only
resolves as part of the energy_report package, not as a standalone script.

--- 2. nginx location block ----------------------------------------------

Add to /etc/nginx-ha-proxy/default.conf, ABOVE the existing catch-all
`location /` block:

    location /energy-report/ {
        alias /opt/home-intelligence/energy_report/output/;
        try_files $uri $uri/ =404;
    }

--- 3. Recreate the ha-proxy container (adds one bind mount) -------------

Docker can't add a mount to a running container -- this stops/removes and
re-runs ha-proxy with its existing flags plus one more. Confirm the exact
current flags first with `docker inspect ha-proxy`, since this reproduces
them from what was true as of this script being written:

    docker stop ha-proxy && docker rm ha-proxy
    docker run -d --name ha-proxy \
      --network host \
      --restart unless-stopped \
      -v /etc/nginx-ha-proxy/default.conf:/etc/nginx/conf.d/default.conf:ro \
      -v /opt/home-intelligence/energy_report/output:/opt/home-intelligence/energy_report/output:ro \
      nginx:alpine

--- 4. Verify -------------------------------------------------------------

    crontab -l                                  # confirm the new entry
    docker inspect ha-proxy --format '{{json .HostConfig.Binds}}'
    curl -s http://domus.ardua.lan/energy-report/ | head -5
EOF
