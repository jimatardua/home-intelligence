"""The Sensus Analytics integration.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md and docs/sensus-analytics-water.md.
"""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import SensusAnalyticsClient
from .const import CONF_BASE_URL
from .coordinator import SensusAnalyticsConfigEntry, SensusAnalyticsCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SensusAnalyticsConfigEntry) -> bool:
    """Set up Sensus Analytics from a config entry."""
    client = SensusAnalyticsClient(entry.data[CONF_BASE_URL], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = SensusAnalyticsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SensusAnalyticsConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: SensusAnalyticsConfigEntry) -> None:
    """Reload the entry when its options change (e.g. unit type, pricing)."""
    await hass.config_entries.async_reload(entry.entry_id)
