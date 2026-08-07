#!/usr/bin/env bash
# Deploys the cigar_dashboard package to domus and prints (does not execute)
# the remaining one-time manual steps -- crontab entry, nginx location
# block, and ha-proxy container recreation -- since those touch shared,
# currently-running infrastructure (HA's own reverse proxy) and are meant
# to be reviewed and run deliberately, not silently applied by this script.
# Mirrors home_dashboard/deploy.sh exactly.
#
# Usage: cigar_dashboard/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/cigar_dashboard"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing cigar_dashboard/ to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'tests' \
  --exclude 'output' \
  --exclude 'cron.log' \
  --exclude 'deploy.sh' \
  "${SCRIPT_DIR}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Sync complete."
echo
echo "The following steps are NOT run automatically -- they touch a live,"
echo "shared container (ha-proxy) and this machine's crontab. Review and"
echo "run them deliberately:"
echo
cat <<'EOF'
--- 0. Run once by hand first, before wiring up cron ------------------------

cd /opt/home-intelligence && python3 -m cigar_dashboard.generate_dashboard --db-path /var/lib/homeassistant/homeassistant/home-assistant_v2.db --output-dir /opt/home-intelligence/cigar_dashboard/output
cat /opt/home-intelligence/cigar_dashboard/output/data.json   # sanity-check real values before automating it

--- 1. Cron entry (crontab -e on domus) -----------------------------------

*/2 * * * * cd /opt/home-intelligence && /usr/bin/python3 -m cigar_dashboard.generate_dashboard --db-path /var/lib/homeassistant/homeassistant/home-assistant_v2.db --output-dir /opt/home-intelligence/cigar_dashboard/output >> /opt/home-intelligence/cigar_dashboard/cron.log 2>&1

Must run as `python3 -m cigar_dashboard.generate_dashboard` with cwd
/opt/home-intelligence (not a direct script path) -- relative imports, and
this package imports energy_report as a sibling
(`from energy_report.ha_recorder import ...`), so both must be siblings
under the same cwd on the Python path, same as home_dashboard.

--- 2. nginx location block ------------------------------------------------

Add to /etc/nginx-ha-proxy/default.conf, alongside the existing
`/dashboard/` and `/energy-report/` blocks:

    location /cigars/ {
        alias /opt/home-intelligence/cigar_dashboard/output/;
        try_files $uri $uri/ =404;
    }

--- 3. Recreate the ha-proxy container (adds one more bind mount) ----------

Docker can't add a mount to a running container. Confirm the CURRENT live
binds first (they may have changed since this script was written):

    docker inspect ha-proxy --format '{{json .HostConfig.Binds}}'

Then reproduce all of those plus the new cigar_dashboard output mount:

    docker stop ha-proxy && docker rm ha-proxy
    docker run -d --name ha-proxy \
      --network host \
      --restart unless-stopped \
      -v /etc/nginx-ha-proxy/certs:/etc/nginx/certs:ro \
      -v /etc/nginx-ha-proxy/default.conf:/etc/nginx/conf.d/default.conf:ro \
      -v /opt/home-intelligence/energy_report/output:/opt/home-intelligence/energy_report/output:ro \
      -v /opt/home-intelligence/home_dashboard/output:/opt/home-intelligence/home_dashboard/output:ro \
      -v /opt/home-intelligence/cigar_dashboard/output:/opt/home-intelligence/cigar_dashboard/output:ro \
      nginx:alpine

--- 4. Verify ---------------------------------------------------------------

    crontab -l                                  # confirm the new entry
    docker inspect ha-proxy --format '{{json .HostConfig.Binds}}'
    curl -s https://domus.ardua.com/cigars/ | head -20
EOF
