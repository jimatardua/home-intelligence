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

# A sanity guard against obviously-wrong values (e.g. a stray extra digit),
# not an attempt to enforce the thermostat's real min/max -- HA/the Nest
# integration itself is the source of truth for that and will reject an
# out-of-range value on its own, surfaced as a normal HomeAssistantError.
MIN_TEMPERATURE = 50
MAX_TEMPERATURE = 90
TEMPERATURE_STEP = 1

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

# Confirmed live (2026-08-18): Home Assistant's `media_player.play_media`
# with `media_content_type: "custom"` sends `media_content_id` to the
# Alexa Media Player integration's `run_custom` -- Amazon's own "text
# command" feature (built for accessibility), which types the phrase to
# the device exactly as if it had been spoken. It bypasses Alexa's speech
# recognition entirely, which is the whole point here.
ALEXA_ENTITY = "media_player.jim_s_echo_studio"  # Family Room Echo Studio
RELAXING_MUSIC_COMMAND = "play relaxing music"

# The set of button actions server.py accepts for the speaker card.
SPEAKER_ACTIONS = ("play_relaxing", "stop")
