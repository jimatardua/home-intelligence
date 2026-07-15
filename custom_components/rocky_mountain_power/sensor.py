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
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import HOURLY_USAGE_ENTITY_ID, HOURLY_USAGE_NAME, HOURLY_USAGE_UNIQUE_ID
from .coordinator import RockyMountainPowerConfigEntry, RockyMountainPowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RockyMountainPowerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Rocky Mountain Power sensor."""
    coordinator = entry.runtime_data
    async_add_entities([RockyMountainPowerHourlyUsageSensor(coordinator)])


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
