"""Sensor platform for the Sensus Analytics integration.

Forked from github.com/zestysoft/sensus_analytics_integration (Apache-2.0)
-- see NOTICE.md. The `UsageConversionMixin` + `DynamicUnitSensorBase`/
`StaticUnitSensorBase` structure below is unchanged from the original --
it was already a reasonable way to avoid repeating unit-conversion logic
across 15 sensor classes. Two smaller pockets of duplication found while
porting this over *are* changed:

- `SensusAnalyticsBillingCostSensor`/`SensusAnalyticsDailyFeeSensor` each
  had their own copy of the same three-tier pricing math (one difference:
  the billing sensor also adds a flat service fee) -- factored into
  `_tiered_usage_cost()` below.
- The four "last hour" sensors (usage/rainfall/temperature/timestamp) each
  independently looped over `hourly_usage_data` computing the current
  local hour and searching for a matching entry -- factored into
  `_current_hour_entry()` below, so each sensor's `native_value` is now a
  one-line lookup.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import SensusAnalyticsConfigEntry, SensusAnalyticsCoordinator

CF_TO_GALLON = 7.48052
CF_PER_CCF = 100  # 1 CCF = 100 cubic feet


async def async_setup_entry(hass: HomeAssistant, entry: SensusAnalyticsConfigEntry, async_add_entities):
    """Set up the Sensus Analytics sensor platform."""
    coordinator = entry.runtime_data
    currency = hass.config.currency
    sensors = [
        SensusAnalyticsDailyUsageSensor(coordinator, entry),
        SensusAnalyticsUsageUnitSensor(coordinator, entry),
        SensusAnalyticsMeterAddressSensor(coordinator, entry),
        SensusAnalyticsLastReadSensor(coordinator, entry),
        SensusAnalyticsMeterLongitudeSensor(coordinator, entry),
        SensusAnalyticsMeterIdSensor(coordinator, entry),
        SensusAnalyticsMeterLatitudeSensor(coordinator, entry),
        MeterOdometerSensor(coordinator, entry),
        SensusAnalyticsBillingUsageSensor(coordinator, entry),
        SensusAnalyticsBillingCostSensor(coordinator, entry, currency),
        SensusAnalyticsDailyFeeSensor(coordinator, entry, currency),
        LastHourUsageSensor(coordinator, entry),
        LastHourRainfallSensor(coordinator, entry),
        LastHourTemperatureSensor(coordinator, entry),
        LastHourTimestampSensor(coordinator, entry),
    ]
    async_add_entities(sensors, True)


def _tiered_usage_cost(
    usage_gallons: float | None,
    tier1_gallons: float,
    tier1_price: float,
    tier2_gallons: float,
    tier2_price: float,
    tier3_price: float,
) -> float:
    """Shared 1-3 tier pricing math for usage-based cost.

    Previously duplicated (with one difference -- a flat service fee) in
    SensusAnalyticsBillingCostSensor and SensusAnalyticsDailyFeeSensor.
    Callers add any flat fee on top of this and round once.
    """
    if usage_gallons is None:
        return 0.0
    if tier1_gallons == 0:
        return usage_gallons * tier1_price
    if tier2_gallons == 0:
        if usage_gallons <= tier1_gallons:
            return usage_gallons * tier1_price
        return tier1_gallons * tier1_price + (usage_gallons - tier1_gallons) * tier2_price
    if tier3_price > 0:
        if usage_gallons <= tier1_gallons:
            return usage_gallons * tier1_price
        if usage_gallons <= tier1_gallons + tier2_gallons:
            return tier1_gallons * tier1_price + (usage_gallons - tier1_gallons) * tier2_price
        return (
            tier1_gallons * tier1_price
            + tier2_gallons * tier2_price
            + (usage_gallons - tier1_gallons - tier2_gallons) * tier3_price
        )
    return 0.0


def _pricing_config(config_entry) -> tuple[float, float, float, float, float]:
    """Extract the (tier1_gallons, tier1_price, tier2_gallons, tier2_price,
    tier3_price) tuple `_tiered_usage_cost` needs, from config entry data."""
    data = config_entry.data
    return (
        data.get("tier1_gallons") or 0,
        data.get("tier1_price"),
        data.get("tier2_gallons") or 0,
        data.get("tier2_price") or 0,
        data.get("tier3_price") or 0,
    )


def _current_hour_entry(hass: HomeAssistant, hourly_data: list[dict]) -> dict | None:
    """The `hourly_usage_data` entry matching the current local hour, or
    None. Shared by all four "last hour" sensors below -- each previously
    had its own copy of this timezone conversion + search loop."""
    if not hourly_data:
        return None
    local_tz = dt_util.get_time_zone(hass.config.time_zone)
    target_hour = datetime.now(local_tz).hour
    for entry in hourly_data:
        entry_time = dt_util.utc_from_timestamp(entry["timestamp"] / 1000).astimezone(local_tz)
        if entry_time.hour == target_hour:
            return entry
    return None


# pylint: disable=too-few-public-methods
class UsageConversionMixin:
    """Mixin to provide usage conversion."""

    # pylint: disable=too-many-return-statements
    def _convert_usage(self, usage, usage_unit=None):
        """Convert usage based on configuration and native unit."""
        if usage is None:
            return None
        if usage_unit is None:
            usage_unit = self.coordinator.data.get("usageUnit")

        config_unit_type = self.coordinator.config_entry.data.get("unit_type")

        try:
            usage_float = float(usage)
        except (ValueError, TypeError):
            return None

        # CF (cubic feet) conversions
        if usage_unit == "CF" and config_unit_type == "gal":
            return round(usage_float * CF_TO_GALLON)
        if usage_unit == "CF" and config_unit_type == "CCF":
            return round(usage_float / CF_PER_CCF, 2)

        # GAL (gallons) conversions
        if usage_unit == "GAL" and config_unit_type == "gal":
            return usage
        if usage_unit == "GAL" and config_unit_type == "CCF":
            # Convert gallons to cubic feet, then to CCF
            return round(usage_float / CF_TO_GALLON / CF_PER_CCF, 2)

        return usage

    def _get_usage_unit(self):
        """Determine the unit of measurement for usage sensors."""
        config_unit_type = self.coordinator.config_entry.data.get("unit_type")

        # Return the user's configured unit type
        # The _convert_usage method handles the actual value conversion
        if config_unit_type == "gal":
            return "gal"
        if config_unit_type == "CCF":
            return "CCF"

        # Fallback to API-reported unit if config is unexpected
        return self.coordinator.data.get("usageUnit")


class DynamicUnitSensorBase(UsageConversionMixin, CoordinatorEntity, SensorEntity):
    """Base class for sensors with dynamic units."""

    def __init__(self, coordinator: SensusAnalyticsCoordinator, entry):
        """Initialize the dynamic unit sensor base."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.entry = entry
        self._unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEFAULT_NAME,
            manufacturer="Unknown",
            model="Water Meter",
        )

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._get_usage_unit()


class StaticUnitSensorBase(UsageConversionMixin, CoordinatorEntity, SensorEntity):
    """Base class for sensors with static units."""

    def __init__(self, coordinator: SensusAnalyticsCoordinator, entry, unit=None, device_class=None):
        """Initialize the static unit sensor base."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.entry = entry
        self._unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEFAULT_NAME,
            manufacturer="Unknown",
            model="Water Meter",
        )
        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class


class SensusAnalyticsDailyUsageSensor(DynamicUnitSensorBase):
    """Representation of the daily usage sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = f"{DEFAULT_NAME} Daily Usage"
        self._attr_unique_id = f"{self._unique_id}_daily_usage"
        self._attr_icon = "mdi:water"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def last_reset(self):
        return dt_util.start_of_local_day()

    @property
    def native_value(self):
        return self._convert_usage(self.coordinator.data.get("dailyUsage"))


class SensusAnalyticsUsageUnitSensor(StaticUnitSensorBase):
    """Representation of the usage unit sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit=None)
        self._attr_name = f"{DEFAULT_NAME} Native Usage Unit"
        self._attr_unique_id = f"{self._unique_id}_usage_unit"

    @property
    def native_value(self):
        return self.coordinator.data.get("usageUnit")


class SensusAnalyticsMeterAddressSensor(StaticUnitSensorBase):
    """Representation of the meter address sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit=None)
        self._attr_name = f"{DEFAULT_NAME} Meter Address"
        self._attr_unique_id = f"{self._unique_id}_meter_address"
        self._attr_icon = "mdi:map-marker"

    @property
    def native_value(self):
        return self.coordinator.data.get("meterAddress1")


class SensusAnalyticsLastReadSensor(StaticUnitSensorBase):
    """Representation of the last read timestamp sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit=None, device_class=SensorDeviceClass.TIMESTAMP)
        self._attr_name = f"{DEFAULT_NAME} Last Read"
        self._attr_unique_id = f"{self._unique_id}_last_read"
        self._attr_icon = "mdi:clock-time-nine"

    @property
    def native_value(self):
        last_read_ts = self.coordinator.data.get("lastRead")
        if not last_read_ts:
            return None
        try:
            return dt_util.utc_from_timestamp(last_read_ts / 1000)
        except (ValueError, TypeError):
            return None


class SensusAnalyticsMeterLongitudeSensor(StaticUnitSensorBase):
    """Representation of the meter longitude sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit="°")
        self._attr_name = f"{DEFAULT_NAME} Meter Longitude"
        self._attr_unique_id = f"{self._unique_id}_meter_longitude"
        self._attr_icon = "mdi:longitude"

    @property
    def native_value(self):
        return self.coordinator.data.get("meterLong")


class SensusAnalyticsMeterIdSensor(StaticUnitSensorBase):
    """Representation of the meter ID sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit=None)
        self._attr_name = f"{DEFAULT_NAME} Meter ID"
        self._attr_unique_id = f"{self._unique_id}_meter_id"
        self._attr_icon = "mdi:account"

    @property
    def native_value(self):
        return self.coordinator.data.get("meterId")


class SensusAnalyticsMeterLatitudeSensor(StaticUnitSensorBase):
    """Representation of the meter latitude sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit="°")
        self._attr_name = f"{DEFAULT_NAME} Meter Latitude"
        self._attr_unique_id = f"{self._unique_id}_meter_latitude"
        self._attr_icon = "mdi:latitude"

    @property
    def native_value(self):
        return self.coordinator.data.get("meterLat")


class MeterOdometerSensor(DynamicUnitSensorBase):
    """Representation of the meter odometer sensor (cumulative total)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = f"{DEFAULT_NAME} Meter Odometer"
        self._attr_unique_id = f"{self._unique_id}_meter_odometer"
        self._attr_icon = "mdi:water"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def last_reset(self):
        return None  # Odometer never resets

    @property
    def native_value(self):
        return self._convert_usage(self.coordinator.data.get("latestReadUsage"))


class SensusAnalyticsBillingUsageSensor(DynamicUnitSensorBase):
    """Representation of the billing-period usage sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = f"{DEFAULT_NAME} Billing Usage"
        self._attr_unique_id = f"{self._unique_id}_billing_usage"
        self._attr_icon = "mdi:water"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def last_reset(self):
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        return datetime.now(local_tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @property
    def native_value(self):
        return self._convert_usage(self.coordinator.data.get("billingUsage"))


class SensusAnalyticsBillingCostSensor(StaticUnitSensorBase):
    """Representation of the billing-period cost sensor."""

    def __init__(self, coordinator, entry, currency):
        super().__init__(coordinator, entry, unit=currency)
        self._attr_name = f"{DEFAULT_NAME} Billing Cost"
        self._attr_unique_id = f"{self._unique_id}_billing_cost"
        self._attr_icon = "mdi:currency-usd"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self):
        usage = self.coordinator.data.get("billingUsage")
        if usage is None:
            return None
        usage_gallons = self._convert_usage(usage)
        tier1_gallons, tier1_price, tier2_gallons, tier2_price, tier3_price = _pricing_config(
            self.coordinator.config_entry
        )
        service_fee = self.coordinator.config_entry.data.get("service_fee")
        cost = service_fee + _tiered_usage_cost(
            usage_gallons, tier1_gallons, tier1_price, tier2_gallons, tier2_price, tier3_price
        )
        return round(cost, 2)


class SensusAnalyticsDailyFeeSensor(StaticUnitSensorBase):
    """Representation of the daily (usage-based, no service fee) cost sensor."""

    def __init__(self, coordinator, entry, currency):
        super().__init__(coordinator, entry, unit=currency)
        self._attr_name = f"{DEFAULT_NAME} Daily Fee"
        self._attr_unique_id = f"{self._unique_id}_daily_fee"
        self._attr_icon = "mdi:currency-usd"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self):
        usage = self.coordinator.data.get("dailyUsage")
        if usage is None:
            return None
        usage_gallons = self._convert_usage(usage)
        tier1_gallons, tier1_price, tier2_gallons, tier2_price, tier3_price = _pricing_config(
            self.coordinator.config_entry
        )
        cost = _tiered_usage_cost(usage_gallons, tier1_gallons, tier1_price, tier2_gallons, tier2_price, tier3_price)
        return round(cost, 2)


class LastHourUsageSensor(DynamicUnitSensorBase):
    """Representation of the last-hour usage sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = f"{DEFAULT_NAME} Last Hour Usage"
        self._attr_unique_id = f"{self._unique_id}_last_hour_usage"
        self._attr_icon = "mdi:water"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL

    @property
    def last_reset(self):
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        return datetime.now(local_tz).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    @property
    def native_value(self):
        entry = _current_hour_entry(self.hass, self.coordinator.data.get("hourly_usage_data", []))
        if entry is None:
            return None
        return self._convert_usage(entry["usage"], entry.get("usage_unit"))


class LastHourRainfallSensor(StaticUnitSensorBase):
    """Representation of the last-hour rainfall sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit="in")
        self._attr_name = f"{DEFAULT_NAME} Last Hour Rainfall"
        self._attr_unique_id = f"{self._unique_id}_last_hour_rainfall"
        self._attr_icon = "mdi:weather-rainy"

    @property
    def native_value(self):
        entry = _current_hour_entry(self.hass, self.coordinator.data.get("hourly_usage_data", []))
        return entry["rain"] if entry else None


class LastHourTemperatureSensor(StaticUnitSensorBase):
    """Representation of the last-hour temperature sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit="°F")
        self._attr_name = f"{DEFAULT_NAME} Last Hour Temperature"
        self._attr_unique_id = f"{self._unique_id}_last_hour_temperature"
        self._attr_icon = "mdi:thermometer"

    @property
    def native_value(self):
        entry = _current_hour_entry(self.hass, self.coordinator.data.get("hourly_usage_data", []))
        return entry["temp"] if entry else None


class LastHourTimestampSensor(StaticUnitSensorBase):
    """Representation of the last-hour timestamp sensor."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, unit=None)
        self._attr_name = f"{DEFAULT_NAME} Last Hour Timestamp"
        self._attr_unique_id = f"{self._unique_id}_last_hour_timestamp"
        self._attr_icon = "mdi:clock-time-nine"

    @property
    def native_value(self):
        entry = _current_hour_entry(self.hass, self.coordinator.data.get("hourly_usage_data", []))
        if entry is None:
            return None
        local_tz = dt_util.get_time_zone(self.hass.config.time_zone)
        entry_time = dt_util.utc_from_timestamp(entry["timestamp"] / 1000).astimezone(local_tz)
        return entry_time.strftime("%Y-%m-%d %H:%M:%S")
