"""The Rocky Mountain Power integration.

No entity platforms: this integration only produces external long-term
statistics (for the Energy Dashboard) and a raw JSON archive on disk. See
docs/rmp-integration.md in the project repo for the full design.
"""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import RockyMountainPowerClient
from .coordinator import RockyMountainPowerConfigEntry, RockyMountainPowerCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: RockyMountainPowerConfigEntry) -> bool:
    """Set up Rocky Mountain Power from a config entry."""
    client = RockyMountainPowerClient(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = RockyMountainPowerCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RockyMountainPowerConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.async_add_executor_job(entry.runtime_data.client.close)
    return True
