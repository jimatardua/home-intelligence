#!/usr/bin/env bash
# Deploys the control_panel package to domus and prints (does not execute)
# the remaining one-time manual steps -- systemd unit install, the nginx
# location blocks, and the ha-proxy container recreate -- since those
# touch host-level state and a live, shared container, meant to be
# reviewed and run deliberately, not silently applied by this script.
#
# Usage: control_panel/deploy.sh
set -euo pipefail

HOST="domus"
REMOTE_DIR="/opt/home-intelligence/control_panel"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing control_panel/ to ${HOST}:${REMOTE_DIR}"
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
echo "The following steps are NOT run automatically -- they touch this"
echo "host's enabled services, nginx config, and a live shared container."
echo "Review and run them deliberately:"
echo
cat <<'EOF'
--- 1. Generate the static shell (one-time -- see generate_page.py's docstring) ---

cd /opt/home-intelligence && python3 -m control_panel.generate_page --output-dir /opt/home-intelligence/control_panel/output

--- 2. systemd unit for the backend (one-time) ---

sudo cp /opt/home-intelligence/control_panel/systemd/control-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now control-panel

--- 3. nginx location blocks -----------------------------------------------

Add to /etc/nginx-ha-proxy/default.conf, ABOVE the existing catch-all
`location /` block:

    location /control/ {
        alias /opt/home-intelligence/control_panel/output/;
        try_files $uri $uri/ =404;
    }
    location /control/api/ {
        proxy_pass http://127.0.0.1:8765/control/api/;
    }

--- 4. Recreate the ha-proxy container (adds one bind mount) ---------------

Docker can't add a mount to a running container -- this stops/removes and
re-runs ha-proxy with its existing flags plus one more. Confirm the exact
current flags first with `docker inspect ha-proxy`, since this reproduces
them from what was true as of this script being written:

    docker stop ha-proxy && docker rm ha-proxy
    docker run -d --name ha-proxy \
      --network host \
      --restart unless-stopped \
      -v /etc/nginx-ha-proxy/certs:/etc/nginx/certs:ro \
      -v /etc/nginx-ha-proxy/default.conf:/etc/nginx/conf.d/default.conf:ro \
      -v /opt/home-intelligence/energy_report/output:/opt/home-intelligence/energy_report/output:ro \
      -v /opt/home-intelligence/home_dashboard/output:/opt/home-intelligence/home_dashboard/output:ro \
      -v /opt/home-intelligence/cigar_dashboard/output:/opt/home-intelligence/cigar_dashboard/output:ro \
      -v /opt/home-intelligence/control_panel/output:/opt/home-intelligence/control_panel/output:ro \
      nginx:alpine

--- 5. Verify -------------------------------------------------------------

    systemctl status control-panel
    curl -s http://127.0.0.1:8765/control/api/thermostat
    curl -s https://domus.ardua.com/control/ | head -5
    curl -s https://domus.ardua.com/control/api/thermostat
EOF
