"""DataUpdateCoordinator for Rocky Mountain Power.

Polls once daily (RMP's interval data lags about a day, so anything faster
is pointless) and re-pulls a trailing window of days per run to catch
late-corrected readings. Each day's raw response is archived to disk before
being imported into HA's long-term statistics, so the archive stays
complete even if the statistics import step fails.

Statistics import needs its cumulative `sum` to be correct even when we
re-import days we've already imported before (RMP occasionally corrects
past readings). To do that safely, the "starting" sum for this run's window
is read from the last statistic strictly *before* the window -- not simply
"whatever the latest statistic in the DB is" -- since the latter would
already include a previous run's contribution from inside this same window
and double-count it.
"""

from __future__ import annotations

from datetime import date, datetime, time as time_of_day, timedelta
import json
import os
from time import monotonic

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import CannotConnect, InvalidAuth, RockyMountainPowerClient, UnexpectedResponse
from .const import (
    ARCHIVE_DIR_NAME,
    DOMAIN,
    HOURLY_USAGE_ENTITY_ID,
    HOURLY_USAGE_NAME,
    LOGGER,
    LOOKBACK_DAYS,
    STATISTIC_ID,
    STATISTIC_NAME,
    UPDATE_INTERVAL,
)

type RockyMountainPowerConfigEntry = ConfigEntry["RockyMountainPowerCoordinator"]


def _reading_start_datetime(reading_date: date, read_time: str) -> datetime:
    """Convert an hour-ending RMP reading into an hour-aligned local datetime.

    `readTime` is hour-ending: "03:00" covers 02:00-03:00, and "24:00"
    covers 23:00-24:00 of the *same* reading_date (it does not roll into
    the next day) -- confirmed against live data.
    """
    hour_ending = int(read_time.split(":")[0])
    start_hour = hour_ending - 1
    naive = datetime.combine(reading_date, time_of_day(hour=start_hour))
    return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


class RockyMountainPowerCoordinator(DataUpdateCoordinator[None]):
    """Coordinates daily RMP polling, archiving, and statistics import."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RockyMountainPowerConfigEntry,
        client: RockyMountainPowerClient,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.last_successful_sync: datetime | None = None
        self.last_poll_duration_seconds: float | None = None
        self.latest_interval_date: date | None = None
        self.latest_hourly_usage: float | None = None

    async def _async_update_data(self) -> None:
        start_time = monotonic()
        archive_dir = self.hass.config.path(ARCHIVE_DIR_NAME)
        await self.hass.async_add_executor_job(_ensure_dir, archive_dir)

        today = dt_util.now().date()
        window_start_date = today - timedelta(days=LOOKBACK_DAYS)

        day_readings: dict[date, list[dict]] = {}
        latest_date_with_data: date | None = None

        for offset in range(LOOKBACK_DAYS, 0, -1):
            target_date = today - timedelta(days=offset)
            try:
                readings = await self.hass.async_add_executor_job(
                    self.client.get_interval_usage, target_date
                )
            except InvalidAuth as err:
                raise UpdateFailed(f"Authentication failed: {err}") from err
            except CannotConnect as err:
                raise UpdateFailed(f"Network error: {err}") from err
            except UnexpectedResponse as err:
                raise UpdateFailed(f"Unexpected response from RMP: {err}") from err

            await self.hass.async_add_executor_job(
                _write_archive, archive_dir, target_date, readings
            )

            if readings:
                day_readings[target_date] = readings
                latest_date_with_data = target_date

        if day_readings:
            await self._async_import_statistics(window_start_date, day_readings)

        self.last_successful_sync = dt_util.utcnow()
        self.last_poll_duration_seconds = monotonic() - start_time
        self.latest_interval_date = latest_date_with_data
        LOGGER.info(
            "Rocky Mountain Power sync complete: %d day(s) with data, latest=%s, took %.1fs",
            len(day_readings),
            self.latest_interval_date,
            self.last_poll_duration_seconds,
        )

    async def _async_import_statistics(
        self, window_start_date: date, day_readings: dict[date, list[dict]]
    ) -> None:
        window_start = datetime.combine(window_start_date, time_of_day()).replace(
            tzinfo=dt_util.DEFAULT_TIME_ZONE
        )
        base_sum = await get_instance(self.hass).async_add_executor_job(
            _get_sum_before, self.hass, window_start
        )
        LOGGER.debug("Base cumulative sum before %s: %s", window_start_date.isoformat(), base_sum)

        entries: list[tuple[datetime, float]] = []
        for target_date in sorted(day_readings):
            for reading in day_readings[target_date]:
                start = _reading_start_datetime(target_date, reading["readTime"])
                entries.append((start, float(reading["usage"])))
        entries.sort(key=lambda item: item[0])

        running_sum = base_sum
        statistics: list[StatisticData] = []
        entity_statistics: list[StatisticData] = []
        for start, usage in entries:
            running_sum += usage
            start_utc = dt_util.as_utc(start)
            statistics.append(StatisticData(start=start_utc, state=usage, sum=running_sum))
            entity_statistics.append(StatisticData(start=start_utc, state=usage, sum=running_sum))

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=STATISTIC_NAME,
            source=DOMAIN,
            statistic_id=STATISTIC_ID,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        LOGGER.debug("Importing %d hourly statistics entries", len(statistics))
        async_add_external_statistics(self.hass, metadata, statistics)

        # Backdate the same hourly values onto a real entity's own
        # statistics too (source="recorder", not our domain) -- purely so
        # third-party dashboard cards that require an entity to exist in
        # hass.states (e.g. apexcharts-card) can chart this data. The
        # external statistic above remains the Energy Dashboard's source of
        # truth; this is a parallel, display-only mirror.
        #
        # has_sum MUST be True here even though we don't need a running
        # total for display: HA's own statistics_during_period silently
        # discards the "state" column from every query whenever a
        # statistic's metadata has has_sum=False (see
        # _extract_metadata_and_discard_impossible_columns in
        # homeassistant/components/recorder/statistics.py) -- confirmed by
        # reading that source directly after apexcharts-card kept getting
        # back empty results despite the raw DB rows being correct. Without
        # this, no historical-statistics-reading dashboard card can ever
        # get a "state" value back for this entity, regardless of what it
        # requests.
        entity_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=HOURLY_USAGE_NAME,
            source="recorder",
            statistic_id=HOURLY_USAGE_ENTITY_ID,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_import_statistics(self.hass, entity_metadata, entity_statistics)

        if entries:
            self.latest_hourly_usage = entries[-1][1]


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write_archive(archive_dir: str, target_date: date, readings: list[dict]) -> None:
    path = os.path.join(archive_dir, f"{target_date.isoformat()}.json")
    payload = {
        "date": target_date.isoformat(),
        "fetched_at": dt_util.utcnow().isoformat(),
        "readings": readings,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _get_sum_before(hass: HomeAssistant, window_start: datetime) -> float:
    """Return the cumulative sum as of the last statistic before window_start.

    Deliberately not `get_last_statistics` (which returns the globally
    latest row) -- when re-importing a window we've already imported
    before, the globally latest row can be *inside* that same window, and
    using it as the base would double-count this run's deltas on top of a
    sum that already includes them.
    """
    result = statistics_during_period(
        hass,
        start_time=dt_util.utc_from_timestamp(0),
        end_time=dt_util.as_utc(window_start),
        statistic_ids={STATISTIC_ID},
        period="hour",
        units=None,
        types={"sum"},
    )
    rows = result.get(STATISTIC_ID)
    if not rows:
        return 0.0
    return float(rows[-1]["sum"])
