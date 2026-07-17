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
