# Current Hardware

## Compute

- Proxmox cluster

## Home Lab

- 4 Intel NUCs
- Synology NAS
- Raspberry Pi devices
- Network switches

## Home Assistant Host (domus)

- Raspberry Pi 4, 8GB
- Debian 12 Bookworm (bare metal, not a VM)
- 458GB USB drive
- 192.168.128.20 / domus.ardua.lan
- HA Supervised 4.0.1, machine type raspberrypi4-64
- Installed with `BYPASS_OS_CHECK=true` — installer wants Debian 13; Debian 12
  works in practice but this is unsupported. Revisit before any Supervisor
  major-version update; do not assume auto-updates are safe unattended.
- Currently located in the basement — no UPS. Planned relocation to the
  family room, see "Planned" below.
- **Needs both Ethernet (primary) and Wi-Fi connected, not just Ethernet.**
  Found the hard way (2026-07-28): disabling Wi-Fi to fix a DNS issue (see
  below) broke connectivity to Matter-over-Thread devices (e.g. the Eve
  Weather sensor) entirely -- domus only picks up a route to the Thread
  mesh's IPv6 prefix via Wi-Fi's Router Advertisements, apparently because
  the Echo acting as Thread border router doesn't propagate that route the
  same way over the wired segment, even though both are on the same IPv4
  subnet. Confirmed directly: with Wi-Fi off, `ip -6 route` had no route to
  the mesh prefix and `ping6` failed with "Network is unreachable"; with
  Wi-Fi back on, the route appeared (`proto ra`, via `wlan0`) and
  connectivity was restored.
- **DNS must resolve consistently across both interfaces.** The real
  incident here wasn't Wi-Fi's fault: pfSense's DHCP server was handing out
  an extra, occasionally-unreliable DNS server (`192.168.128.3`) alongside
  the primary one, which `systemd-resolved` aggregated across both
  interfaces into an inconsistent resolver list -- causing chronic,
  intermittent lookup failures for Tesla Fleet, weather-upload automations,
  and anything else calling an external host. Disabling Wi-Fi entirely was
  briefly used as a workaround and made a good test case, but was the wrong
  fix (see above) -- the actual fix was correcting the DHCP server's
  configuration to hand out one consistent, reliable DNS server, which
  makes running both interfaces safe again.
- **Tesla vehicles don't answer ICMP ping, even fully awake and online.**
  Found live (2026-07-29) debugging why the Tesla WiFi-arrival automation
  never fired: a `ping` binary_sensor against each car's DHCP-reserved IP
  stayed `off` through a real arrival, even though the car's
  `device_tracker` (Tesla Fleet cloud data) correctly showed it home.
  Confirmed via `gateway.ardua.lan` (pfSense) directly -- `arp -a` showed a
  fresh ARP entry for the car's MAC and `pfctl -s state` showed live
  established TCP/UDP connections to Tesla's own cloud IPs, yet `ping` to
  that same IP got 100% loss from both the gateway itself and domus. Not a
  sleep/timing race, not a DHCP mismatch -- the car simply never answers
  ICMP echo, full stop. Fixed by reading presence from pfSense's own ARP
  table instead of pinging: a dedicated pfSense user (`ha-arp-monitor`)
  with an SSH key restricted via `authorized_keys`'
  `command="/usr/sbin/arp -an"` (forced command -- overrides anything the
  client requests, no shell, no argument injection surface, verified
  directly against the live account). Two real pfSense gotchas hit setting
  this up: (1) pfSense locks a user's Unix account (`pw lock`, blocking SSH
  entirely regardless of password) unless it holds one of a specific set of
  privileges -- `User - System: Shell account access` is required just to
  avoid the lock, even though the forced command means the granted shell is
  never actually reachable; (2) pfSense regenerates `~/.ssh/authorized_keys`
  from its own `config.xml` on every User Manager save, silently deleting
  any key placed on the filesystem by hand -- the (restricted) key must be
  entered into the GUI's "Authorized SSH Keys" field to survive future
  saves. `binary_sensor.carport_jim_s_tesla_wifi` /
  `..._irina_s_tesla_wifi` (the old `ping` sensors) are superseded by
  `..._arp` sensors of the same shape; the old `ping` integration entries
  can be removed from Settings > Devices & Services once confirmed stable.

## Cigar Storage Monitoring

- 3x Govee H5075 Bluetooth LE thermo-hygrometer -- `TH01` in the Whynter
  wineador (primary storage), `TH02` in an old wooden humidor repurposed as
  a "drybox," `TH03` loose on the desk (ambient reference). Fixed MACs
  (not randomized), decoded via community-reverse-engineered manufacturer
  data -- see `docs/govee-cigar-monitor.md`.
- Raspberry Pi 3, `mrteeny.ardua.lan` -- lives permanently in the office,
  in BLE range of all 3 sensors (domus is not). Runs `govee_collector` as
  a systemd service (`User=jramsey`, no elevated Bluetooth privileges
  needed -- confirmed live, not assumed), publishing to an MQTT broker
  (Mosquitto, installed as an HA add-on on domus) rather than the
  SSH-forced-command pattern used for the pfSense ARP bridge -- mrteeny is
  a general-purpose box under full control, unlike pfSense, so MQTT is the
  better-fit standard pattern here. Eventually planned to be Velcro-mounted
  to the back of the humidor.
- **Adding any MQTT `logins` entry to the Mosquitto add-on disables
  anonymous access broker-wide** -- broke HA's own "Add MQTT integration"
  flow (which defaults to blank username/password) until a second,
  dedicated `homeassistant` login was added alongside the collector's own
  `govee-collector` login. Full writeup in `docs/govee-cigar-monitor.md`.
- **Do not run another independent BLE-scanning script on mrteeny while
  `govee-collector` is live.** Found live (2026-08-08): a second script
  reading the same 3 sensors, left running overnight, coincided with the
  collector going ~8 hours silently stale and later failing to restart
  with `org.bluez.Error.InProgress` -- BlueZ has no clean multi-client
  discovery story on one adapter. Needed a real adapter reset to recover
  (`hciconfig hci0 down`/`up` + `systemctl restart bluetooth`). The
  collector now has a self-healing watchdog for silent stalls, but not for
  a fully stuck adapter -- see `docs/govee-cigar-monitor.md`'s "Known
  risks" for the manual recovery command if this happens again.

## HVAC

- Nest Thermostat
- Nest temperature sensor

## Vehicles

- Tesla Model Y (Red, 2026)
- Tesla Model Y (Gray, 2023)

## Electrical

Main house panel

Pool house panel

Tesla Wall Connector connected through pool house panel.

## Planned

- Emporia Vue
- Relocate domus from the basement to the family room (next to the
  existing Pi, `ralph`) -- motivated by needing real Thread border router
  connectivity for a future outdoor weather sensor (see roadmap.md Phase 3);
  a basement border router would need its signal to cross both a floor and
  an exterior wall to reach an outdoor device. Needs a small UPS at the new
  location, since domus currently has none. Move via clean shutdown
  (`ha host shutdown` / `sudo shutdown -h now`), not a live power pull.
