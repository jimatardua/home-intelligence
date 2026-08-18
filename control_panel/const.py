"""Entity IDs and fixed config for the control panel.

Confirmed live against the real Home Assistant instance (not assumed):
`climate.family_room_family_room` for the thermostat, and the 7 cover
entities via HA's own area/entity registries (`.storage/core.area_registry`,
`.storage/core.entity_registry`) -- 4 in the `office` area, 3 in `dining`,
all on the `neosmartblinds` integration.
"""

from __future__ import annotations

HA_BASE_URL = "http://127.0.0.1:8123"

CLIMATE_ENTITY = "climate.family_room_family_room"

# Deliberately excludes "heat_cool" -- the user confirmed it's never used
# and it needs two setpoints (a low/high range) instead of one, which
# would meaningfully complicate this page for a mode nobody wants.
HVAC_MODES: list[str] = ["off", "cool", "heat"]
HVAC_MODE_LABELS: dict[str, str] = {"off": "Off", "cool": "Cool", "heat": "Heat"}

OFFICE_COVERS: list[str] = [
    "cover.office_1",
    "cover.office_2",
    "cover.office_3",
    "cover.office_4",
]
DINING_COVERS: list[str] = [
    "cover.dining_left",
    "cover.dining_middle",
    "cover.dining_right",
]

ROOM_COVERS: dict[str, list[str]] = {
    "office": OFFICE_COVERS,
    "dining": DINING_COVERS,
}
ROOM_LABELS: dict[str, str] = {"office": "Office", "dining": "Dining"}

# Confirmed live (2026-08-18): repeated `cover.set_cover_position` calls
# silently no-op after the first one from a given extreme (matches the
# user's own report of the HA UI's "mid" button leaving the "up" button
# greyed out afterward) -- `open_cover`/`close_cover` don't have this
# problem. Only the mid position has no dedicated service to fall back
# on, so that's the one case that has to use set_cover_position.
COVER_POSITION_SERVICE: dict[int, str] = {
    100: "open_cover",
    0: "close_cover",
}
COVER_MID_POSITION = 50
