"""Binary sensor platform for Rocky Mountain Power.

Single entity surfacing whether the daily sync has gone stale/stuck -- see
health.py for the decision logic and docs/rmp-integration.md's "Staleness
alert" section for why this exists.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import SYNC_PROBLEM_NAME, SYNC_PROBLEM_UNIQUE_ID, SYNC_PROBLEM_ENTITY_ID
from .coordinator import RockyMountainPowerConfigEntry, RockyMountainPowerCoordinator
from .health import HEALTH_STATUS_OK, compute_sync_status


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RockyMountainPowerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Rocky Mountain Power binary sensor."""
    coordinator = entry.runtime_data
    async_add_entities([RockyMountainPowerSyncProblemBinarySensor(coordinator)])


class RockyMountainPowerSyncProblemBinarySensor(
    CoordinatorEntity[RockyMountainPowerCoordinator], BinarySensorEntity
):
    """On when the daily sync has gone stale or stuck."""

    _attr_has_entity_name = True
    _attr_name = SYNC_PROBLEM_NAME
    _attr_unique_id = SYNC_PROBLEM_UNIQUE_ID
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    entity_id = SYNC_PROBLEM_ENTITY_ID

    def __init__(self, coordinator: RockyMountainPowerCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def is_on(self) -> bool:
        status = compute_sync_status(self.coordinator.last_successful_sync, dt_util.utcnow())
        return status != HEALTH_STATUS_OK
