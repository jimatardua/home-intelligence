#!/usr/bin/env bash
# Deploys the home_dashboard package to domus and prints (does not execute)
# the remaining one-time manual steps -- crontab entry, nginx location
# block, and ha-proxy container recreation -- since those touch shared,
# currently-running infrastructure (HA's own reverse proxy) and are meant
# to be reviewed and run deliberately, not silently applied by this script.
#
# Usage: home_dashboard/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/home_dashboard"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing home_dashboard/ to ${HOST}:${REMOTE_DIR}"
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
--- 1. Cron entry (crontab -e on domus) -----------------------------------

*/2 * * * * cd /opt/home-intelligence && /usr/bin/python3 -m home_dashboard.generate_dashboard --db-path /var/lib/homeassistant/homeassistant/home-assistant_v2.db --output-dir /opt/home-intelligence/home_dashboard/output >> /opt/home-intelligence/home_dashboard/cron.log 2>&1

Runs every 2 minutes -- cheap enough (local DB reads + one NWS API call).
Must run as `python3 -m home_dashboard.generate_dashboard` with cwd
/opt/home-intelligence (not a direct script path), same reason as
energy_report: relative imports, and this package also imports
energy_report as a sibling (`from energy_report.disaggregation import ...`
etc.), so both must be siblings under the same cwd on the Python path.

`astral` must be installed on domus's host Python via apt, not pip --
Debian's PEP 668 blocks a bare `pip install` here, and apt's own
`python3-astral` package (1.6.1, an old pre-3.x API -- `sun_times.py` is
written against that exact API, not the newer one) is what's actually
installed: `sudo apt-get install -y python3-astral`. `requests` is already
present the same way (apt's `python3-requests`), already required by the
RMP integration.

--- 2. nginx location block ------------------------------------------------

Add to /etc/nginx-ha-proxy/default.conf, ABOVE the existing catch-all
`location /` block (alongside the existing `/energy-report/` block):

    location /dashboard/ {
        alias /opt/home-intelligence/home_dashboard/output/;
        try_files $uri $uri/ =404;
    }

--- 3. Recreate the ha-proxy container (adds one more bind mount) ----------

Docker can't add a mount to a running container. Current live binds
(confirmed via `docker inspect ha-proxy` as of writing -- a TLS certs mount
has been added since the energy_report deploy, alongside its own output
mount):

    /etc/nginx-ha-proxy/certs:/etc/nginx/certs:ro
    /opt/home-intelligence/energy_report/output:/opt/home-intelligence/energy_report/output:ro
    /etc/nginx-ha-proxy/default.conf:/etc/nginx/conf.d/default.conf:ro

Reproduce all of these plus the new home_dashboard output mount -- confirm
the exact current flags first with `docker inspect ha-proxy` in case
anything else has changed since this script was written:

    docker stop ha-proxy && docker rm ha-proxy
    docker run -d --name ha-proxy \
      --network host \
      --restart unless-stopped \
      -v /etc/nginx-ha-proxy/certs:/etc/nginx/certs:ro \
      -v /etc/nginx-ha-proxy/default.conf:/etc/nginx/conf.d/default.conf:ro \
      -v /opt/home-intelligence/energy_report/output:/opt/home-intelligence/energy_report/output:ro \
      -v /opt/home-intelligence/home_dashboard/output:/opt/home-intelligence/home_dashboard/output:ro \
      nginx:alpine

--- 4. Verify ---------------------------------------------------------------

    crontab -l                                  # confirm the new entry
    docker inspect ha-proxy --format '{{json .HostConfig.Binds}}'
    curl -s https://domus.ardua.com/dashboard/ | head -5
EOF
