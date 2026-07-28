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
