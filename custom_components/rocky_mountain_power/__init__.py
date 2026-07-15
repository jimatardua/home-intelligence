"""The Rocky Mountain Power integration.

Primarily produces external long-term statistics (for the Energy
Dashboard) and a raw JSON archive on disk. One sensor entity exists purely
so third-party dashboard cards can chart the same data -- see sensor.py
and docs/rmp-integration.md in the project repo for the full design.
"""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import RockyMountainPowerClient
from .coordinator import RockyMountainPowerConfigEntry, RockyMountainPowerCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: RockyMountainPowerConfigEntry) -> bool:
    """Set up Rocky Mountain Power from a config entry."""
    client = RockyMountainPowerClient(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = RockyMountainPowerCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RockyMountainPowerConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded
