"""Sensor platform for Rocky Mountain Power.

This entity exists purely so third-party dashboard cards that require a
real hass.states entry (e.g. apexcharts-card) can chart RMP's hourly usage
-- the external statistic in coordinator.py deliberately has no backing
entity (that's what lets it correctly represent backdated hourly data),
and cards that check hass.states can never resolve a colon-form external
statistic_id.

Its *live* state is just "the latest known hourly value", for basic
display. The actually-useful backdated hourly curve lives in this entity's
own long-term statistics, injected by the coordinator via
async_import_statistics(source="recorder") -- deliberately NOT via
state_class, since setting state_class would opt this entity into HA's
own automatic statistics compilation from its live state history, which
would conflict with (and get overwritten by, until the next poll) the
explicitly-backdated data. See coordinator.py and docs/rmp-integration.md.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    HOURLY_USAGE_ENTITY_ID,
    HOURLY_USAGE_NAME,
    HOURLY_USAGE_UNIQUE_ID,
    HOURS_SINCE_SYNC_ENTITY_ID,
    HOURS_SINCE_SYNC_NAME,
    HOURS_SINCE_SYNC_UNIQUE_ID,
    SYNC_STATUS_ENTITY_ID,
    SYNC_STATUS_NAME,
    SYNC_STATUS_UNIQUE_ID,
)
from .coordinator import RockyMountainPowerConfigEntry, RockyMountainPowerCoordinator
from .health import compute_sync_status


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RockyMountainPowerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Rocky Mountain Power sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            RockyMountainPowerHourlyUsageSensor(coordinator),
            RockyMountainPowerSyncStatusSensor(coordinator),
            RockyMountainPowerHoursSinceSyncSensor(coordinator),
        ]
    )


class RockyMountainPowerHourlyUsageSensor(
    CoordinatorEntity[RockyMountainPowerCoordinator], SensorEntity
):
    """Latest known hourly usage; real statistics live in long-term storage."""

    _attr_has_entity_name = True
    _attr_name = HOURLY_USAGE_NAME
    _attr_unique_id = HOURLY_USAGE_UNIQUE_ID
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    entity_id = HOURLY_USAGE_ENTITY_ID

    def __init__(self, coordinator: RockyMountainPowerCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.latest_hourly_usage


class RockyMountainPowerSyncStatusSensor(
    CoordinatorEntity[RockyMountainPowerCoordinator], SensorEntity
):
    """"ok"/"stale"/"stuck" -- see health.py. Diagnostic detail for whoever's
    debugging a problem lives in the attributes, not the state string."""

    _attr_has_entity_name = True
    _attr_name = SYNC_STATUS_NAME
    _attr_unique_id = SYNC_STATUS_UNIQUE_ID
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "stale", "stuck"]
    entity_id = SYNC_STATUS_ENTITY_ID

    def __init__(self, coordinator: RockyMountainPowerCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def native_value(self) -> str:
        return compute_sync_status(self.coordinator.last_successful_sync, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict:
        last_successful_sync = self.coordinator.last_successful_sync
        last_exception = self.coordinator.last_exception
        return {
            "last_successful_sync": last_successful_sync.isoformat() if last_successful_sync else None,
            "last_exception": str(last_exception) if last_exception else None,
        }


class RockyMountainPowerHoursSinceSyncSensor(
    CoordinatorEntity[RockyMountainPowerCoordinator], SensorEntity
):
    """Hours since the last successful sync -- daily polling makes hours the
    readable unit here, unlike govee_collector's near-real-time seconds."""

    _attr_has_entity_name = True
    _attr_name = HOURS_SINCE_SYNC_NAME
    _attr_unique_id = HOURS_SINCE_SYNC_UNIQUE_ID
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 1
    entity_id = HOURS_SINCE_SYNC_ENTITY_ID

    def __init__(self, coordinator: RockyMountainPowerCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def native_value(self) -> float | None:
        last_successful_sync = self.coordinator.last_successful_sync
        if last_successful_sync is None:
            return None
        return (dt_util.utcnow() - last_successful_sync).total_seconds() / 3600
