#!/usr/bin/env bash
# Deploys the govee_collector package to mrteeny and prints (does not
# execute) the remaining one-time manual steps -- apt installs, the MQTT
# password file, and the systemd unit install/enable -- since those touch
# host-level state (installed packages, a secret file, an enabled service)
# meant to be reviewed and run deliberately, not silently applied by this
# script.
#
# Usage: govee_collector/deploy.sh
set -euo pipefail

HOST="mrteeny.ardua.lan"
REMOTE_DIR="/opt/home-intelligence/govee_collector"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Syncing govee_collector/ to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'tests' \
  --exclude 'deploy.sh' \
  --exclude '*.log' \
  --exclude 'auto_reset_state.json' \
  "${SCRIPT_DIR}/" "${HOST}:${REMOTE_DIR}/"

echo "==> Sync complete."
echo
echo "The following steps are NOT run automatically -- they touch this"
echo "host's installed packages, a secret file, and an enabled systemd"
echo "service. Review and run them deliberately:"
echo
cat <<'EOF'
--- 1. System packages (one-time) -------------------------------------------

sudo apt-get install -y python3-bleak python3-paho-mqtt

Installed via apt, not pip -- this environment is PEP 668
externally-managed (`pip install` fails outright), same reason
python3-astral is apt-installed on domus rather than pip-installed.

--- 2. MQTT credentials (one-time, do NOT commit this file) ------------------

Create the dedicated MQTT login in the Mosquitto add-on first (see
docs/govee-cigar-monitor.md), then on mrteeny:

    sudo tee /etc/govee-collector.env >/dev/null <<'ENV'
    MQTT_PASSWORD=<the password set for the govee-collector MQTT login>
    ENV
    sudo chmod 600 /etc/govee-collector.env

--- 3. systemd unit -----------------------------------------------------------

sudo cp /opt/home-intelligence/govee_collector/systemd/govee-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now govee-collector

--- 4. Nightly preemptive BLE adapter reset (one-time) ------------------------

hci0 has wedged into a silent org.bluez.Error.InProgress state three times
now (2026-08-10, 2026-08-14, 2026-08-21) with no contending process any
time -- see docs/govee-cigar-monitor.md's "Known risks" section. This runs
the same manual reset sequence that fixed it every time, nightly, before
the watchdog ever needs to notice:

    chmod +x /opt/home-intelligence/govee_collector/ble_nightly_reset.sh
    crontab -e
    # add:
    0 4 * * * /opt/home-intelligence/govee_collector/ble_nightly_reset.sh >> /opt/home-intelligence/govee_collector/ble_reset_cron.log 2>&1

--- 5. On-detection auto-reset (one-time) ---------------------------------------

The nightly reset only covers overnight -- the 2026-08-21 wedge happened
mid-afternoon and needed a manual SSH-in. This detects collector.py's own
"stuck" health status (parsed from journalctl, no dependency on
domus/HA/MQTT reachability) and runs the same reset script automatically,
with a tiered backoff (5min/15min/60min) if a reset doesn't actually fix
it. See docs/govee-cigar-monitor.md.

    crontab -e
    # add:
    */2 * * * * cd /opt/home-intelligence && /usr/bin/python3 -m govee_collector.ble_auto_reset >> /opt/home-intelligence/govee_collector/ble_auto_reset_cron.log 2>&1

--- 6. Verify ------------------------------------------------------------------

journalctl -u govee-collector -f
mosquitto_sub -h domus.ardua.lan -u govee-collector -P '<password>' -t 'govee/#' -v
EOF
