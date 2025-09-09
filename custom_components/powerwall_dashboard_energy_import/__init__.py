"""Powerwall Dashboard Energy Import integration."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone

# Recorder imports removed - we now use Spook's service instead
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import slugify

from .config_flow import OptionsFlowHandler
from .const import (
    CONF_DB_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PW_NAME,
    CONF_USERNAME,
    DEFAULT_PW_NAME,
    DOMAIN,
)
from .influx_client import InfluxClient

PLATFORMS: list[str] = ["sensor"]
_LOGGER = logging.getLogger(__name__)

BACKFILL_FIELDS = {
    # Daily sensors (existing - keep for backward compatibility)
    "home_usage_daily": "home",
    "solar_generated_daily": "solar",
    "grid_imported_daily": "from_grid",
    "grid_exported_daily": "to_grid",
    "battery_discharged_daily": "from_pw",
    "battery_charged_daily": "to_pw",
    # Main sensors (newly added)
    "home_usage": "home",
    "solar_generated": "solar",
    "grid_imported": "from_grid",
    "grid_exported": "to_grid",
    "battery_discharged": "from_pw",
    "battery_charged": "to_pw",
    # Monthly sensors (newly added)
    "home_usage_monthly": "home",
    "solar_generated_monthly": "solar",
    "grid_imported_monthly": "from_grid",
    "grid_exported_monthly": "to_grid",
    "battery_discharged_monthly": "from_pw",
    "battery_charged_monthly": "to_pw",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Powerwall Dashboard Energy Import from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = InfluxClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        database=entry.data[CONF_DB_NAME],
    )
    connected = await hass.async_add_executor_job(client.connect)
    if not connected:
        _LOGGER.error("Failed to connect to InfluxDB during setup")
        return False

    pw_name = entry.data.get(CONF_PW_NAME, DEFAULT_PW_NAME)
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "config": entry.data,
        "pw_name": pw_name,
        "backfill_active": False,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "backfill"):
        hass.services.async_register(DOMAIN, "backfill", async_handle_backfill)

    if not hass.services.has_service(DOMAIN, "migrate_from_teslemetry"):
        hass.services.async_register(
            DOMAIN, "migrate_from_teslemetry", async_handle_teslemetry_migration
        )

    if not hass.services.has_service(DOMAIN, "backfill_from_date_to_now"):
        hass.services.async_register(
            DOMAIN, "backfill_from_date_to_now", async_handle_backfill_to_now
        )

    return True


async def async_handle_backfill(call: ServiceCall):  # noqa: C901
    """Handle the service call to backfill historical data."""
    _LOGGER.info("=== BACKFILL SERVICE STARTING ===")
    _LOGGER.info("Backfill service called: %s", call.data)
    hass = call.hass

    use_all = call.data.get("all", False)
    start_str = call.data.get("start")
    end_str = call.data.get("end")
    sensor_prefix = call.data.get("sensor_prefix")
    overwrite_existing = call.data.get("overwrite_existing", False)

    _LOGGER.info(
        "Parameters - all: %s, start: %s, end: %s, prefix: %s, overwrite: %s",
        use_all,
        start_str,
        end_str,
        sensor_prefix,
        overwrite_existing,
    )

    if not use_all and not start_str:
        _LOGGER.error(
            "Backfill service requires either 'all' or 'start' to be specified."
        )
        return

    target_entry: ConfigEntry | None = None
    available_entries = hass.config_entries.async_entries(DOMAIN)
    _LOGGER.info("Found %d integration entries", len(available_entries))

    if sensor_prefix:
        _LOGGER.info("Looking for entry with sensor_prefix: %s", sensor_prefix)
        for entry in available_entries:
            entry_prefix_raw = entry.data.get(
                CONF_PW_NAME, entry.entry_id.replace("-", "_")
            )
            # Convert to entity-safe format using Home Assistant's official slugify
            entry_prefix = slugify(entry_prefix_raw, separator="_")
            _LOGGER.info(
                "Checking entry %s with raw prefix: %s, entity prefix: %s",
                entry.entry_id,
                entry_prefix_raw,
                entry_prefix,
            )
            if entry_prefix == sensor_prefix:
                target_entry = entry
                break
        if not target_entry:
            _LOGGER.error(
                "Could not find a Powerwall integration with sensor_prefix: %s",
                sensor_prefix,
            )
            return
    else:
        if len(available_entries) > 1:
            _LOGGER.warning(
                "Multiple Powerwall integrations found. Using the first one. Specify 'sensor_prefix' to target a specific one."
            )
        target_entry = available_entries[0]

    _LOGGER.info("Using config entry: %s", target_entry.entry_id)

    store = hass.data[DOMAIN][target_entry.entry_id]
    client: InfluxClient = store["client"]
    series_source = target_entry.options.get("series_source", "autogen.http")

    try:
        if end_str:
            # Handle both simple date format and ISO timestamp format
            if "T" in end_str:
                end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00")).date()
            else:
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        else:
            end_date = date.today()
        if use_all:
            first_ts = await hass.async_add_executor_job(
                client.get_first_timestamp, series_source
            )
            if not first_ts:
                _LOGGER.error("Could not determine the first timestamp from InfluxDB.")
                return
            start_date = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).date()
        else:
            if not start_str:
                _LOGGER.error("Start date is required when 'all' is not specified.")
                return
            # Handle both simple date format and ISO timestamp format
            if "T" in start_str:
                start_date = datetime.fromisoformat(
                    start_str.replace("Z", "+00:00")
                ).date()
            else:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()

    except ValueError as e:
        _LOGGER.error("Invalid date format for start/end: %s", e)
        return

    _LOGGER.info(
        "Starting backfill from %s to %s for %s",
        start_date,
        end_date,
        sensor_prefix or "default",
    )

    ent_reg = async_get_entity_registry(hass)
    _LOGGER.info("Starting entity processing...")

    try:
        _LOGGER.info("Starting backfill operation (sensors will remain active)")
        # No pause needed - both systems use same InfluxDB data source
        for sensor_id_suffix, influx_field in BACKFILL_FIELDS.items():
            _LOGGER.info("Processing sensor: %s -> %s", sensor_id_suffix, influx_field)
            unique_id = (
                f"{target_entry.entry_id}:powerwall_dashboard_{sensor_id_suffix}"
            )
            _LOGGER.info("Looking for unique_id: %s", unique_id)

            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            _LOGGER.info("Found entity_id: %s", entity_id)

            if not entity_id:
                _LOGGER.warning("Could not find entity for unique_id: %s", unique_id)
                continue

            entity_entry = ent_reg.async_get(entity_id)
            if not entity_entry:
                _LOGGER.warning(
                    "Could not find entity registry entry for: %s", entity_id
                )
                continue

            _LOGGER.info("Found entity entry for: %s", entity_id)

            _LOGGER.debug("Processing backfill for %s (%s)", entity_id, influx_field)
            _LOGGER.info(
                "Entity details - ID: %s, Name: %s, Original Name: %s",
                entity_id,
                entity_entry.name,
                entity_entry.original_name,
            )

            # metadata = StatisticMetaData(
            #     has_mean=False,
            #     has_sum=True,
            #     name=entity_entry.name or entity_entry.original_name,
            #     source=DOMAIN,
            #     statistic_id=entity_id,
            #     unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            # )

            # _LOGGER.info("Statistics metadata: %s", metadata)

            # Use Home Assistant's configured timezone
            ha_timezone = hass.config.time_zone
            tz = zoneinfo.ZoneInfo(ha_timezone) if ha_timezone else timezone.utc

            stats = []

            # Handle overwrite logic BEFORE calculating statistics
            cumulative_base = 0.0

            # Determine if we should overwrite based on whether any date in range is current day
            today = datetime.now(tz).date()
            has_current_day = start_date <= today <= end_date
            should_overwrite = overwrite_existing and not has_current_day

            if has_current_day and overwrite_existing:
                _LOGGER.warning(
                    "Current day %s is in range %s to %s with overwrite_existing=true. Switching to append mode to preserve live sensor data.",
                    today.isoformat(),
                    start_date.isoformat(),
                    end_date.isoformat(),
                )

            if should_overwrite:
                _LOGGER.warning(
                    "Overwrite enabled - clearing existing statistics for %s from %s to %s",
                    entity_id,
                    start_date,
                    end_date,
                )

                # Get the cumulative base BEFORE purging to maintain continuity
                try:
                    from datetime import timedelta

                    # Get statistics from just before the start date
                    # We want the cumulative value at the end of the day BEFORE start_date
                    end_of_previous_day = datetime.combine(
                        start_date - timedelta(days=1), datetime.max.time()
                    )
                    end_of_previous_day = end_of_previous_day.replace(tzinfo=tz)

                    # Query statistics up to end of previous day
                    from typing import Any, cast

                    # FIRST HOUR BOUNDARY FIX: Preserve existing cumulative baseline to prevent massive backwards jumps
                    # Instead of forcing HA alignment (which causes 5000+ kWh backwards jumps), preserve
                    # the existing statistical baseline from before our backfill period starts

                    try:
                        # Get the LAST statistic BEFORE our backfill start date to preserve existing baseline
                        # This prevents massive backwards jumps at the first hour of backfill
                        # We need to query database directly since get_last_statistics returns the most recent, not before a date
                        from homeassistant.components.recorder.statistics import (
                            get_last_statistics,
                            statistics_during_period,
                        )

                        # Get all statistics up to the day before backfill start
                        end_time = datetime.combine(
                            start_date, time.min, tzinfo=tz
                        ) - timedelta(seconds=1)
                        start_time = end_time - timedelta(
                            days=30
                        )  # Look back 30 days max

                        baseline_stats = await hass.async_add_executor_job(
                            statistics_during_period,  # type: ignore[arg-type]
                            hass,
                            start_time,
                            end_time,
                            [entity_id],
                            "hour",
                            {"sum"},
                            {"sum"},
                        )

                        if (
                            baseline_stats
                            and entity_id in baseline_stats
                            and baseline_stats[entity_id]
                        ):
                            # Find the LAST statistic before our backfill start (latest timestamp)
                            entity_stats = baseline_stats[entity_id]
                            if entity_stats:
                                last_baseline_stat = entity_stats[
                                    -1
                                ]  # Last entry is most recent
                                if (
                                    "sum" in last_baseline_stat
                                    and last_baseline_stat["sum"] is not None
                                ):
                                    cumulative_base = float(last_baseline_stat["sum"])
                                    baseline_time = last_baseline_stat.get(
                                        "start", "unknown"
                                    )
                                    _LOGGER.warning(
                                        "BASELINE PRESERVATION: Found existing baseline %.3f kWh at %s (before backfill start) - preserving to prevent backwards jumps",
                                        cumulative_base,
                                        baseline_time,
                                    )
                                else:
                                    cumulative_base = 0.0
                                    _LOGGER.warning(
                                        "BASELINE PRESERVATION: Found baseline stat but no sum value, using cumulative_base=0.0"
                                    )
                            else:
                                cumulative_base = 0.0
                                _LOGGER.warning(
                                    "BASELINE PRESERVATION: No baseline statistics found in period, using cumulative_base=0.0"
                                )
                        else:
                            cumulative_base = 0.0
                            _LOGGER.warning(
                                "BASELINE PRESERVATION: No existing statistics found before backfill, using cumulative_base=0.0"
                            )

                    except Exception as e:
                        _LOGGER.warning(
                            "BASELINE PRESERVATION: Failed to get existing baseline: %s, using cumulative_base=0.0",
                            e,
                        )
                        cumulative_base = 0.0

                except Exception as e:
                    _LOGGER.warning(
                        "HA ALIGNMENT: Could not analyze cumulative base alignment for %s: %s, using 0.0",
                        entity_id,
                        e,
                    )
                    cumulative_base = 0.0

                # Now purge the existing statistics
                try:
                    # Use Home Assistant's recorder.purge_entities service to clear statistics
                    await hass.services.async_call(
                        "recorder",
                        "purge_entities",
                        {
                            "entity_id": [entity_id],
                            "keep_days": 0,  # Remove all data
                        },
                    )
                    _LOGGER.info(
                        "Successfully cleared existing statistics for %s", entity_id
                    )

                except Exception as e:
                    _LOGGER.error(
                        "Failed to clear existing statistics for %s: %s", entity_id, e
                    )
                    return
            else:
                # Get the last cumulative value before start_date to maintain continuity
                try:
                    # Query the last statistic before our start date
                    from datetime import timedelta
                    from typing import Any, cast

                    from homeassistant.components.recorder.statistics import (
                        get_last_statistics,
                        statistics_during_period,
                    )

                    # Get all statistics up to the day before backfill start
                    end_time = datetime.combine(
                        start_date, time.min, tzinfo=tz
                    ) - timedelta(seconds=1)
                    start_time = end_time - timedelta(days=30)  # Look back 30 days max

                    baseline_stats = await hass.async_add_executor_job(
                        statistics_during_period,  # type: ignore[arg-type]
                        hass,
                        start_time,
                        end_time,
                        [entity_id],
                        "hour",
                        {"sum"},
                        {"sum"},
                    )

                    if (
                        baseline_stats
                        and entity_id in baseline_stats
                        and baseline_stats[entity_id]
                    ):
                        # Find the LAST statistic before our backfill start (latest timestamp)
                        entity_stats = baseline_stats[entity_id]
                        if entity_stats:
                            last_baseline_stat = entity_stats[
                                -1
                            ]  # Last entry is most recent
                            if (
                                "sum" in last_baseline_stat
                                and last_baseline_stat["sum"] is not None
                            ):
                                cumulative_base = float(last_baseline_stat["sum"])
                                baseline_time = last_baseline_stat.get(
                                    "start", "unknown"
                                )
                                _LOGGER.info(
                                    "APPEND MODE: Found existing cumulative base: %.3f kWh at %s (before backfill start)",
                                    cumulative_base,
                                    baseline_time,
                                )
                            else:
                                cumulative_base = 0.0
                                _LOGGER.warning(
                                    "APPEND MODE: Found baseline stat but no sum value, using cumulative_base=0.0"
                                )
                        else:
                            cumulative_base = 0.0
                            _LOGGER.warning(
                                "APPEND MODE: No baseline statistics found in period, using cumulative_base=0.0"
                            )

                except Exception as e:
                    _LOGGER.warning(
                        "Could not get existing cumulative base for %s, starting from 0: %s",
                        entity_id,
                        e,
                    )
                    cumulative_base = 0.0

            current_date: date = start_date
            while current_date <= end_date:
                _LOGGER.warning("=== PROCESSING DAY %s ===", current_date)
                _LOGGER.warning(
                    "Starting cumulative_base for %s: %.3f kWh",
                    current_date,
                    cumulative_base,
                )

                # CRITICAL FIX: For current day, only backfill up to current hour
                # This prevents writing future hour statistics that block live data
                current_datetime = datetime.now(tz)
                is_current_day = current_date == today

                # Get realistic hourly energy data instead of artificially splitting daily total
                hourly_values = await hass.async_add_executor_job(
                    client.get_hourly_kwh,
                    influx_field,
                    current_date,
                    series_source,
                    ha_timezone or "UTC",
                )

                _LOGGER.info(
                    "Retrieved %d hourly values for %s: %s",
                    len(hourly_values),
                    current_date,
                    [f"h{i}={v:.3f}" for i, v in enumerate(hourly_values) if v > 0][
                        :5
                    ],  # Show first 5 non-zero hours
                )
                _LOGGER.info(
                    "Using timezone %s for statistics timestamps (current date: %s)",
                    ha_timezone or "UTC",
                    current_date,
                )

                daily_total = sum(hourly_values)
                if daily_total > 0:
                    _LOGGER.info(
                        "DEBUG: Processing %s with total %.3f kWh across %d hours",
                        current_date,
                        daily_total,
                        len([h for h in hourly_values if h > 0]),
                    )

                    # Build cumulative statistics from actual hourly data
                    cumulative_progress = 0.0

                    # CRITICAL FIX: Stop at last complete hour to avoid partial hour collisions
                    max_hour = 24
                    if is_current_day:
                        current_hour = current_datetime.hour
                        # Stop at last complete hour - live sensors handle current partial hour
                        max_hour = current_hour  # Backfill complete hours only (0 to current_hour-1)
                        _LOGGER.info(
                            "Current day %s: backfilling complete hours 0-%d (current time: %s, live sensors handle partial hour %d)",
                            current_date,
                            current_hour - 1 if current_hour > 0 else 0,
                            current_datetime.strftime("%H:%M"),
                            current_hour,
                        )

                    for hour in range(max_hour):
                        hourly_energy = hourly_values[hour]
                        cumulative_progress += hourly_energy

                        stat_start = datetime(
                            current_date.year,
                            current_date.month,
                            current_date.day,
                            hour,
                            0,  # Minutes must be 0 for HA statistics
                            0,  # Seconds must be 0 for HA statistics
                            tzinfo=tz,
                        )

                        # Calculate cumulative total at this hour
                        cumulative_at_hour = cumulative_base + cumulative_progress

                        # CRITICAL FIX: Add STATE field to coordinate with HA's TOTAL_INCREASING calculation
                        # For daily sensors, state represents the sensor reading (cumulative since midnight)
                        # This aligns our statistics with how live sensors report their state
                        sensor_state = cumulative_progress  # Daily total since midnight (not lifetime cumulative)

                        # For TOTAL_INCREASING sensors, sum should always be cumulative
                        # regardless of sensor naming - HA handles daily calculations automatically
                        stats.append(
                            {
                                "start": stat_start,
                                "sum": cumulative_at_hour,  # Always cumulative for TOTAL_INCREASING
                                "state": sensor_state,  # Coordinates with live sensor state
                            }
                        )

                        # Debug logging for first day and first few hours, plus any hour with significant energy
                        if current_date == start_date and hour < 6:
                            _LOGGER.info(
                                "DEBUG: Hour %d - timestamp: %s, hourly: %.3f kWh, cumulative: %.3f kWh",
                                hour,
                                stat_start.isoformat(),
                                hourly_energy,
                                cumulative_at_hour,
                            )

                    # Update cumulative base for next day
                    old_cumulative_base = cumulative_base
                    cumulative_base += daily_total
                    _LOGGER.info(
                        "End of day %s: daily_total=%.3f, old_base=%.3f, new_base=%.3f",
                        current_date,
                        daily_total,
                        old_cumulative_base,
                        cumulative_base,
                    )
                current_date += timedelta(days=1)

            if stats:
                _LOGGER.info("Importing %d statistics for %s", len(stats), entity_id)
                _LOGGER.info("Sample stat: %s", stats[0] if stats else "None")

                # SMART BOUNDARY SYNC: Detect and fix discontinuities without causing cumulative base inflation
                try:
                    from homeassistant.components.recorder.statistics import (
                        get_last_statistics,
                    )

                    # Get the final backfilled statistic
                    final_backfilled_stat = stats[-1] if stats else None
                    if final_backfilled_stat and isinstance(
                        final_backfilled_stat["start"], datetime
                    ):
                        final_start = final_backfilled_stat["start"]
                        final_sum = final_backfilled_stat["sum"]

                        _LOGGER.info(
                            "SMART BOUNDARY SYNC: Final backfilled sum is %.3f kWh at %s",
                            final_sum,
                            final_start.isoformat(),
                        )

                        # Check if there are existing live statistics AFTER our backfill end
                        next_hour_start = final_start + timedelta(hours=1)

                        # Query for live statistics that come after our backfilled data
                        future_stats = await hass.async_add_executor_job(
                            cast(Any, get_last_statistics),
                            hass,
                            10,  # Get multiple statistics to find the right one
                            entity_id,
                            True,  # Convert units
                            {"sum"},  # Only need sum
                        )

                        if future_stats and entity_id in future_stats:
                            entity_stats = future_stats[entity_id]
                            if entity_stats and len(entity_stats) > 0:
                                # Find the first live statistic AFTER our backfill end
                                next_live_stat = None
                                for stat in entity_stats:
                                    if "start" in stat and stat["start"]:
                                        stat_time_str = stat["start"]
                                        if isinstance(stat_time_str, str):
                                            stat_time = datetime.fromisoformat(
                                                stat_time_str.replace("Z", "+00:00")
                                            )
                                        else:
                                            stat_time = stat_time_str

                                        if (
                                            isinstance(stat_time, datetime)
                                            and stat_time >= next_hour_start
                                        ):
                                            next_live_stat = stat
                                            break

                                if (
                                    next_live_stat
                                    and "sum" in next_live_stat
                                    and next_live_stat["sum"] is not None
                                ):
                                    live_sum = float(next_live_stat["sum"])
                                    final_sum_value = (
                                        float(final_sum)  # type: ignore[arg-type]
                                        if final_sum is not None
                                        else 0.0
                                    )
                                    discontinuity = final_sum_value - live_sum

                                    if (
                                        abs(discontinuity) > 5.0
                                    ):  # More than 5 kWh discontinuity
                                        _LOGGER.warning(
                                            "SMART BOUNDARY SYNC: Detected %.3f kWh discontinuity between final backfilled (%.3f) and first live (%.3f) at %s",
                                            discontinuity,
                                            final_sum,
                                            live_sum,
                                            next_live_stat.get("start", "unknown"),
                                        )

                                        # Apply SMART adjustment - reduce ALL backfilled stats by the discontinuity
                                        # This preserves relative progression while aligning the final value
                                        for stat in stats:
                                            current_sum = (
                                                float(stat["sum"])  # type: ignore[arg-type]
                                                if stat["sum"] is not None
                                                else 0.0
                                            )
                                            stat["sum"] = max(
                                                0.0, current_sum - discontinuity
                                            )

                                        _LOGGER.warning(
                                            "SMART BOUNDARY SYNC: Applied %.3f kWh downward adjustment to align with live data. Final sum: %.3f → %.3f kWh",
                                            discontinuity,
                                            final_sum_value,
                                            final_sum_value - discontinuity,
                                        )
                                    else:
                                        _LOGGER.info(
                                            "SMART BOUNDARY SYNC: No significant discontinuity detected (%.3f kWh)",
                                            discontinuity,
                                        )
                                else:
                                    _LOGGER.info(
                                        "SMART BOUNDARY SYNC: No live statistics found after backfill end"
                                    )
                            else:
                                _LOGGER.info(
                                    "SMART BOUNDARY SYNC: No future statistics available"
                                )
                        else:
                            _LOGGER.info(
                                "SMART BOUNDARY SYNC: No statistics found for boundary check"
                            )

                except Exception as e:
                    _LOGGER.warning(
                        "SMART BOUNDARY SYNC: Could not perform boundary synchronization check: %s",
                        e,
                    )

                # Check if Spook's recorder.import_statistics service is available
                if not hass.services.has_service("recorder", "import_statistics"):
                    _LOGGER.error(
                        "Backfill requires Spook integration for recorder.import_statistics service. "
                        "Install Spook from https://github.com/frenck/spook or HACS. "
                        "The built-in HA statistics API cannot import data for entities with state_class set."
                    )
                    continue

                # Overwrite logic has been moved to before statistics calculation

                # Process in batches to avoid exceeding HA's 32KB service call limit
                batch_size = 100  # Process 100 statistics entries at a time
                total_imported = 0

                for i in range(0, len(stats), batch_size):
                    batch = stats[i : i + batch_size]
                    try:
                        service_data = {
                            "statistic_id": entity_id,
                            "source": "recorder",
                            "has_mean": False,
                            "has_sum": True,
                            "unit_of_measurement": "kWh",
                            "name": entity_entry.name or entity_entry.original_name,
                            "stats": batch,
                        }
                        # Debug: log first few entries of first batch
                        if i == 0 and len(batch) > 0:
                            _LOGGER.info(
                                "DEBUG: First batch sample for %s - First 3 entries:",
                                entity_id,
                            )
                            for j, stat_dict in enumerate(batch[:3]):
                                # stat_dict is a dict with statistics data
                                start_time = stat_dict["start"]  # type: ignore[assignment]
                                sum_value = (
                                    float(stat_dict["sum"])  # type: ignore[arg-type]
                                    if stat_dict["sum"] is not None
                                    else 0.0
                                )
                                _LOGGER.info(
                                    "  Entry %d: start=%s, sum=%.3f",
                                    j + 1,
                                    start_time.isoformat()
                                    if hasattr(start_time, "isoformat")
                                    else start_time,
                                    sum_value,
                                )

                        await hass.services.async_call(
                            "recorder", "import_statistics", service_data
                        )
                        total_imported += len(batch)
                        _LOGGER.info(
                            "Imported batch %d-%d (%d entries) for %s",
                            i + 1,
                            i + len(batch),
                            len(batch),
                            entity_id,
                        )
                    except Exception as e:
                        _LOGGER.error(
                            "Failed to import batch %d-%d for %s: %s",
                            i + 1,
                            i + len(batch),
                            entity_id,
                            e,
                        )
                        _LOGGER.error("Batch sample: %s", batch[0] if batch else "None")

                _LOGGER.info(
                    "Successfully imported %d total statistics via Spook for %s",
                    total_imported,
                    entity_id,
                )
            else:
                _LOGGER.info("No new statistics to import for %s", entity_id)

    finally:
        _LOGGER.info("Backfill operation completed")


async def async_handle_backfill_to_now(call: ServiceCall):
    """Handle the pause-and-complete backfill service - from date to current time."""
    start_str = call.data.get("start")

    if not start_str:
        _LOGGER.error("backfill_from_date_to_now requires 'start' parameter")
        return

    try:
        datetime.strptime(start_str, "%Y-%m-%d").date()  # Validate date format
        end_date = datetime.now().date()
    except ValueError as e:
        _LOGGER.error("Invalid date format for start: %s", e)
        return

    # Use same logic as main backfill but with end_date = today
    await async_handle_backfill(
        ServiceCall(
            domain=call.domain,
            service=call.service,
            data={
                **call.data,
                "end": end_date.strftime("%Y-%m-%d"),
                "overwrite_existing": False,  # Always use append mode for safety
            },
            context=call.context,
            hass=call.hass,
        )
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        store = hass.data[DOMAIN].pop(entry.entry_id, None)
        if store and (client := store.get("client")):
            await hass.async_add_executor_job(client.close)

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "backfill")
            hass.services.async_remove(DOMAIN, "migrate_from_teslemetry")

    return unload_ok


async def async_handle_teslemetry_migration(call: ServiceCall):  # noqa: C901
    """Handle the service call to migrate Teslemetry historical statistics."""
    _LOGGER.info("=== TESLEMETRY MIGRATION SERVICE STARTING ===")
    _LOGGER.info("Migration service called: %s", call.data)
    hass = call.hass

    auto_discover = call.data.get("auto_discover", True)
    entity_prefix = call.data.get("entity_prefix")
    sensor_prefix = call.data.get("sensor_prefix")
    entity_mapping = call.data.get("entity_mapping", {})
    start_date_str = call.data.get("start_date")
    end_date_str = call.data.get("end_date")
    dry_run = call.data.get("dry_run", False)
    overwrite_existing = call.data.get("overwrite_existing", False)
    merge_strategy = call.data.get("merge_strategy", "prioritize_influx")
    auto_backfill = call.data.get("auto_backfill", True)

    _LOGGER.info(
        "Migration parameters - auto_discover: %s, entity_prefix: %s, sensor_prefix: %s, dry_run: %s, merge_strategy: %s, auto_backfill: %s",
        auto_discover,
        entity_prefix,
        sensor_prefix,
        dry_run,
        merge_strategy,
        auto_backfill,
    )

    # Check if Spook's recorder.import_statistics service is available
    if not hass.services.has_service("recorder", "import_statistics"):
        _LOGGER.error(
            "Teslemetry migration requires Spook integration for recorder.import_statistics service. "
            "Install Spook from https://github.com/frenck/spook or HACS."
        )
        return

    # Get entity registry
    ent_reg = async_get_entity_registry(hass)

    try:
        # Parse date range if provided
        start_time = None
        end_time = None
        # Use Home Assistant's configured timezone instead of hardcoded UTC
        ha_timezone = hass.config.time_zone
        tz = zoneinfo.ZoneInfo(ha_timezone) if ha_timezone else timezone.utc
        _LOGGER.info(
            "Using timezone %s for Teslemetry migration date range",
            ha_timezone or "UTC",
        )

        if start_date_str:
            start_time = (
                datetime.strptime(start_date_str, "%Y-%m-%d")
                .replace(tzinfo=tz)
                .isoformat()
            )
        if end_date_str:
            end_time = (
                datetime.strptime(end_date_str, "%Y-%m-%d")
                .replace(tzinfo=tz)
                .isoformat()
            )

        _LOGGER.info(
            "Migration time range: %s to %s",
            start_time or "beginning",
            end_time or "present",
        )

        # Find target Powerwall Dashboard config entry
        target_entry: ConfigEntry | None = None
        available_entries = hass.config_entries.async_entries(DOMAIN)
        _LOGGER.info(
            "Found %d Powerwall Dashboard integration entries", len(available_entries)
        )

        if sensor_prefix:
            _LOGGER.info("Looking for entry with sensor_prefix: %s", sensor_prefix)
            for entry in available_entries:
                entry_prefix_raw = entry.data.get(
                    CONF_PW_NAME, entry.entry_id.replace("-", "_")
                )
                # Convert to entity-safe format using Home Assistant's official slugify
                entry_prefix = slugify(entry_prefix_raw, separator="_")
                _LOGGER.info(
                    "Checking entry %s with raw prefix: %s, entity prefix: %s",
                    entry.entry_id,
                    entry_prefix_raw,
                    entry_prefix,
                )
                if entry_prefix == sensor_prefix:
                    target_entry = entry
                    break
            if not target_entry:
                _LOGGER.error(
                    "Could not find a Powerwall integration with sensor_prefix: %s",
                    sensor_prefix,
                )
                return
        else:
            if len(available_entries) > 1:
                _LOGGER.warning(
                    "Multiple Powerwall integrations found. Using the first one. Specify 'sensor_prefix' to target a specific one."
                )
            target_entry = available_entries[0]

        _LOGGER.info("Using target config entry: %s", target_entry.entry_id)

        # Auto-discover Teslemetry entities if enabled
        teslemetry_entities = {}
        if auto_discover:
            if entity_prefix:
                _LOGGER.info(
                    "Auto-discovering Tesla energy entities with prefix: %s",
                    entity_prefix,
                )
            else:
                _LOGGER.info(
                    "Auto-discovering Teslemetry energy entities using legacy pattern matching..."
                )
            teslemetry_entities = await _discover_teslemetry_entities(
                hass, ent_reg, target_entry, entity_prefix
            )
            _LOGGER.info(
                "Found %d potential Tesla energy entities",
                len(teslemetry_entities),
            )

        # Add any manual entity mappings
        if entity_mapping:
            teslemetry_entities.update(entity_mapping)
            _LOGGER.info("Added %d manual entity mappings", len(entity_mapping))

        if not teslemetry_entities:
            _LOGGER.warning(
                "No Teslemetry entities found to migrate. Check auto-discovery or provide manual mapping."
            )
            return

        # Process each Teslemetry entity
        total_migrated = 0
        for teslemetry_entity_id, our_entity_id in teslemetry_entities.items():
            _LOGGER.info(
                "Processing migration: %s → %s", teslemetry_entity_id, our_entity_id
            )

            try:
                # Extract statistics from Teslemetry entity
                statistics_data = await _extract_teslemetry_statistics(
                    hass, teslemetry_entity_id, start_time, end_time
                )

                if not statistics_data:
                    _LOGGER.info("No statistics found for %s", teslemetry_entity_id)
                    continue

                _LOGGER.info(
                    "Extracted %d statistics entries from %s",
                    len(statistics_data),
                    teslemetry_entity_id,
                )

                if dry_run:
                    _LOGGER.info(
                        "DRY RUN: Would import %d statistics for %s",
                        len(statistics_data),
                        our_entity_id,
                    )
                    total_migrated += len(statistics_data)
                    continue

                # Check if target entity exists and has statistics
                if not overwrite_existing:
                    existing_stats = await _check_existing_statistics(
                        hass, our_entity_id, start_time, end_time
                    )
                    if existing_stats:
                        _LOGGER.warning(
                            "Target entity %s already has statistics. Use overwrite_existing=true to replace.",
                            our_entity_id,
                        )
                        continue

                # Get target entity metadata
                target_entity = ent_reg.async_get(our_entity_id)
                if not target_entity:
                    _LOGGER.warning(
                        "Target entity %s not found in registry. Skipping migration.",
                        our_entity_id,
                    )
                    continue

                # Import statistics using Spook
                await _import_statistics_via_spook(
                    hass, our_entity_id, target_entity, statistics_data
                )

                total_migrated += len(statistics_data)
                _LOGGER.info(
                    "Successfully migrated %d statistics from %s to %s",
                    len(statistics_data),
                    teslemetry_entity_id,
                    our_entity_id,
                )

            except Exception as e:
                _LOGGER.error("Failed to migrate %s: %s", teslemetry_entity_id, e)
                continue

        if dry_run:
            _LOGGER.info(
                "DRY RUN COMPLETE: Would migrate %d total statistics entries",
                total_migrated,
            )
        else:
            _LOGGER.info(
                "MIGRATION COMPLETE: Successfully migrated %d total statistics entries",
                total_migrated,
            )

        # Auto-trigger backfill if enabled and migration was successful
        if auto_backfill and total_migrated > 0 and not dry_run:
            _LOGGER.info("=== AUTO-BACKFILL PHASE STARTING ===")
            _LOGGER.info(
                "Triggering backfill to overwrite migrated data with higher-quality InfluxDB data where available"
            )
            
            try:
                await _trigger_auto_backfill(
                    hass, target_entry, sensor_prefix, overwrite_existing
                )
            except Exception as e:
                _LOGGER.error(
                    "Auto-backfill failed, but migration was successful: %s", e
                )
                # Don't re-raise - migration succeeded even if backfill failed

    except Exception as e:
        _LOGGER.error("Migration service failed: %s", e)
        raise


def _get_teslemetry_patterns() -> tuple[list[str], dict[str, str]]:
    """Get Tesla/Teslemetry entity patterns and mappings."""
    teslemetry_patterns = [
        # Home energy patterns
        "home_energy",
        "home_consumption",
        "home_usage",
        "load",
        # Solar energy patterns
        "solar_energy",
        "solar_production",
        "solar_generated",
        "pv",
        # Battery energy patterns
        "battery_energy",
        "battery_charge",
        "battery_discharge",
        "powerwall",
        # Grid energy patterns
        "grid_energy",
        "grid_import",
        "grid_export",
        "utility",
    ]

    our_entity_patterns = {
        # Daily sensor mappings (existing - keep for backward compatibility)
        "home": "home_usage_daily",
        "home_energy": "home_usage_daily",
        "home_consumption": "home_usage_daily",
        "home_usage": "home_usage_daily",
        "load": "home_usage_daily",
        "solar": "solar_generated_daily",
        "solar_energy": "solar_generated_daily",
        "solar_production": "solar_generated_daily",
        "solar_generated": "solar_generated_daily",
        "pv": "solar_generated_daily",
        "battery_charge": "battery_charged_daily",
        "battery_energy_in": "battery_charged_daily",
        "battery_discharge": "battery_discharged_daily",
        "battery_energy_out": "battery_discharged_daily",
        "powerwall": "battery_discharged_daily",
        "grid_import": "grid_imported_daily",
        "grid_energy_in": "grid_imported_daily",
        "utility": "grid_imported_daily",
        "grid_export": "grid_exported_daily",
        "grid_energy_out": "grid_exported_daily",
        # Main sensor mappings (newly added)
        "home_main": "home_usage",
        "solar_main": "solar_generated",
        "battery_charge_main": "battery_charged",
        "battery_discharge_main": "battery_discharged",
        "grid_import_main": "grid_imported",
        "grid_export_main": "grid_exported",
        # Monthly sensor mappings (newly added)
        "home_monthly": "home_usage_monthly",
        "solar_monthly": "solar_generated_monthly",
        "battery_charge_monthly": "battery_charged_monthly",
        "battery_discharge_monthly": "battery_discharged_monthly",
        "grid_import_monthly": "grid_imported_monthly",
        "grid_export_monthly": "grid_exported_monthly",
    }

    return teslemetry_patterns, our_entity_patterns


def _match_tesla_entity_to_mapping(
    entity_id: str, entity_prefix: str | None, our_entity_patterns: dict[str, str]
) -> str | None:
    """Match a Tesla entity ID to our entity mapping patterns."""
    entity_lower = entity_id.lower()

    # Check entity prefix matching if specified
    if entity_prefix:
        prefixes = [p.strip().lower() for p in entity_prefix.split(",")]
        entity_matches = any(prefix in entity_lower for prefix in prefixes)
        if not entity_matches:
            return None

    # Priority matching - exact matches first
    priority_patterns = [
        ("solar_energy", "solar_generated_daily"),
        ("solar_production", "solar_generated_daily"),
        ("solar_generated", "solar_generated_daily"),
        ("grid_export", "grid_exported_daily"),
        ("grid_import", "grid_imported_daily"),
        ("battery_charge", "battery_charged_daily"),
        ("battery_discharge", "battery_discharged_daily"),
        ("home_energy", "home_usage_daily"),
        ("home_usage", "home_usage_daily"),
    ]

    for pattern, mapping in priority_patterns:
        if pattern in entity_lower:
            return mapping

    # Fallback to fuzzy matching
    for pattern, mapping in our_entity_patterns.items():
        if pattern in entity_lower:
            return mapping

    return None


async def _discover_teslemetry_entities(
    hass: HomeAssistant,
    ent_reg,
    target_entry: ConfigEntry,
    entity_prefix: str | None = None,
) -> dict:
    """Discover Teslemetry energy entities and map them to our entities.

    Args:
        hass: Home Assistant instance
        ent_reg: Entity registry
        target_entry: Target Powerwall Dashboard config entry to use for entity mapping
        entity_prefix: Optional entity prefix to search for (e.g., 'my_home', 'tesla_site')
    """
    teslemetry_mapping = {}

    _LOGGER.debug(
        "Starting entity discovery - entity_prefix: %s, scanning entity registry with %d entities",
        entity_prefix or "None (using legacy discovery)",
        len(ent_reg.entities),
    )

    teslemetry_patterns, our_entity_patterns = _get_teslemetry_patterns()

    # Scan entity registry for potential Teslemetry entities
    for entity in ent_reg.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue

        # Look for Tesla/Teslemetry entities with energy characteristics
        entity_lower = entity.entity_id.lower()

        # Check legacy discovery if no entity_prefix specified
        if not entity_prefix:
            entity_matches = "tesla" in entity_lower or "teslemetry" in entity_lower
            if not entity_matches:
                continue

        # Try to match this entity to our patterns
        our_pattern = _match_tesla_entity_to_mapping(
            entity.entity_id, entity_prefix, our_entity_patterns
        )

        if our_pattern:
            # Use the sensor prefix to build our entity ID
            sensor_prefix_raw = target_entry.data.get(
                CONF_PW_NAME, target_entry.entry_id.replace("-", "_")
            )
            # Convert to entity-safe format using Home Assistant's official slugify
            sensor_prefix = slugify(sensor_prefix_raw, separator="_")
            our_entity_id = f"sensor.{sensor_prefix}_{our_pattern}"
            teslemetry_mapping[entity.entity_id] = our_entity_id
            _LOGGER.debug(
                "Mapped Tesla entity: %s -> %s (pattern: %s, sensor_prefix: %s)",
                entity.entity_id,
                our_entity_id,
                our_pattern,
                sensor_prefix,
            )

    _LOGGER.info(
        "Entity discovery complete - found %d mappings: %s",
        len(teslemetry_mapping),
        list(teslemetry_mapping.keys()) if teslemetry_mapping else "None",
    )
    return teslemetry_mapping


def _check_missing_hours(day_stats: list[dict]) -> None:
    """Check for missing hours in daily statistics."""
    hours_present = {
        stat["time"][:2] for stat in day_stats if isinstance(stat["time"], str)
    }
    missing_hours = {f"{h:02d}" for h in range(24)} - hours_present
    if missing_hours:
        _LOGGER.debug("  Missing hours: %s", sorted(missing_hours))


def _check_large_jumps(day_stats: list[dict]) -> None:
    """Check for large jumps in cumulative values."""
    sums = [
        float(s["sum"])
        for s in day_stats
        if s["sum"] is not None and isinstance(s["sum"], (int, float))
    ]
    if len(sums) > 1:
        jumps = [
            sums[i + 1] - sums[i] for i in range(len(sums) - 1) if sums[i + 1] > sums[i]
        ]
        if jumps:
            max_jump = max(jumps)
            if max_jump > 10:
                _LOGGER.debug("  Large cumulative jump detected: %.1f kWh", max_jump)


def _log_first_last_entries(day_stats: list[dict]) -> None:
    """Log first and last entries for the day."""
    if len(day_stats) > 0:
        first_sum = day_stats[0]["sum"]
        first_sum_val = float(first_sum) if isinstance(first_sum, (int, float)) else 0.0
        _LOGGER.debug(
            "  First entry: %s - sum=%.1f", day_stats[0]["time"], first_sum_val
        )

        if len(day_stats) > 1:
            last_sum = day_stats[-1]["sum"]
            last_sum_val = (
                float(last_sum) if isinstance(last_sum, (int, float)) else 0.0
            )
            _LOGGER.debug(
                "  Last entry:  %s - sum=%.1f", day_stats[-1]["time"], last_sum_val
            )


def _check_time_gaps(day_stats: list[dict]) -> None:
    """Check for time gaps in daily statistics."""
    for i in range(1, len(day_stats)):
        curr_time = day_stats[i]["time"]
        prev_time = day_stats[i - 1]["time"]
        if isinstance(curr_time, str) and isinstance(prev_time, str):
            try:
                curr_hour = int(curr_time[:2])
                prev_hour = int(prev_time[:2])
                hour_gap = curr_hour - prev_hour
                if hour_gap > 2 or (hour_gap < 0 and curr_hour + 24 - prev_hour > 2):
                    gap_hours = hour_gap if hour_gap > 0 else curr_hour + 24 - prev_hour
                    _LOGGER.debug(
                        "  DATA GAP: %s -> %s (gap of %d hours)",
                        prev_time,
                        curr_time,
                        gap_hours,
                    )

                    curr_sum = day_stats[i]["sum"]
                    prev_sum = day_stats[i - 1]["sum"]
                    if isinstance(curr_sum, (int, float)) and isinstance(
                        prev_sum, (int, float)
                    ):
                        _LOGGER.debug(
                            "    Sum jump: %.1f -> %.1f (diff: %.1f kWh)",
                            prev_sum,
                            curr_sum,
                            curr_sum - prev_sum,
                        )
            except (ValueError, IndexError):
                continue


def _analyze_daily_statistics(day_stats: list[dict], date_str: str) -> None:
    """Analyze daily statistics for patterns and gaps."""
    _LOGGER.debug("Date %s: %d entries", date_str, len(day_stats))
    _check_missing_hours(day_stats)
    _check_large_jumps(day_stats)
    _log_first_last_entries(day_stats)
    _check_time_gaps(day_stats)


def _get_statistics_service_data(
    start_time: str | None, end_time: str | None, entity_id: str
) -> dict:
    """Prepare service data for statistics API call."""
    service_data = {
        "statistic_ids": [entity_id],
        "period": "hour",
        "types": ["sum", "mean", "min", "max"],
    }

    if start_time:
        service_data["start_time"] = start_time
    if end_time:
        service_data["end_time"] = end_time

    return service_data


def _extract_statistics_from_response(
    response: dict, entity_id: str
) -> list[dict] | None:
    """Extract statistics data from recorder service response."""
    if (
        response
        and isinstance(response, dict)
        and "statistics" in response
        and isinstance(response["statistics"], dict)
        and entity_id in response["statistics"]
    ):
        result = response["statistics"][entity_id]
        if isinstance(result, list):
            return [stat for stat in result if isinstance(stat, dict)]
    return None


def _get_recent_statistics(filtered_result: list[dict], hours: int = 72) -> list[dict]:
    """Filter statistics to recent timeframe."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    cutoff_time = now - timedelta(hours=hours)

    recent_stats = []
    for stat in filtered_result:
        if "start" in stat and isinstance(stat["start"], str):
            try:
                stat_time = datetime.fromisoformat(stat["start"].replace("Z", "+00:00"))
                if stat_time >= cutoff_time:
                    recent_stats.append(stat)
            except (ValueError, AttributeError):
                pass

    return recent_stats


def _group_statistics_by_date(recent_stats: list[dict]) -> dict:
    """Group statistics by date for analysis."""
    from collections import defaultdict
    from datetime import datetime

    stats_by_date = defaultdict(list)

    for stat in recent_stats:
        if (
            isinstance(stat, dict)
            and "start" in stat
            and isinstance(stat["start"], str)
        ):
            try:
                stat_time = datetime.fromisoformat(stat["start"].replace("Z", "+00:00"))
                date_str = stat_time.date().isoformat()
                stats_by_date[date_str].append(
                    {
                        "time": stat_time.strftime("%H:%M"),
                        "sum": stat.get("sum"),
                        "mean": stat.get("mean"),
                        "timestamp": stat["start"],
                    }
                )
            except (ValueError, AttributeError):
                continue

    return stats_by_date


async def _extract_teslemetry_statistics(
    hass: HomeAssistant,
    entity_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict]:
    """Extract statistics from a Teslemetry entity using recorder.get_statistics."""
    try:
        service_data = _get_statistics_service_data(start_time, end_time, entity_id)

        # Call recorder.get_statistics service
        response = await hass.services.async_call(
            "recorder",
            "get_statistics",
            service_data,
            blocking=True,
            return_response=True,
        )

        _LOGGER.debug("Statistics API response for %s: %s", entity_id, response)

        # Extract statistics data
        filtered_result = (
            _extract_statistics_from_response(response, entity_id) if response else None
        )
        if not filtered_result:
            return []

        # Analyze patterns in recent data
        recent_stats = _get_recent_statistics(filtered_result)

        if recent_stats:
            _LOGGER.debug(
                "=== RECENT TESLEMETRY DATA ANALYSIS (last 72 hours) for %s ===",
                entity_id,
            )
            _LOGGER.debug("Found %d recent statistics entries", len(recent_stats))

            # Group by day and analyze patterns
            stats_by_date = _group_statistics_by_date(recent_stats)

            # Log daily patterns
            for date_str, day_stats in sorted(stats_by_date.items()):
                _analyze_daily_statistics(day_stats, date_str)

            _LOGGER.debug("=== END RECENT DATA ANALYSIS ===")

        return filtered_result

    except Exception as e:
        _LOGGER.error("Failed to extract statistics for %s: %s", entity_id, e)
        return []


async def _check_existing_statistics(
    hass: HomeAssistant,
    entity_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> bool:
    """Check if target entity already has statistics in the specified time range."""
    try:
        service_data = {
            "statistic_ids": [entity_id],
            "period": "hour",
            "types": ["sum", "mean", "min", "max"],
        }

        if start_time:
            service_data["start_time"] = start_time
        if end_time:
            service_data["end_time"] = end_time

        response = await hass.services.async_call(
            "recorder",
            "get_statistics",
            service_data,
            blocking=True,
            return_response=True,
        )

        return bool(
            response
            and isinstance(response, dict)
            and "statistics" in response
            and isinstance(response["statistics"], dict)
            and entity_id in response["statistics"]
            and response["statistics"][entity_id]
        )

    except Exception as e:
        _LOGGER.debug("Could not check existing statistics for %s: %s", entity_id, e)
        return False


async def _import_statistics_via_spook(
    hass: HomeAssistant, entity_id: str, entity_entry, statistics_data: list
):
    """Import statistics data using Spook's recorder.import_statistics service."""
    if not statistics_data:
        return

    # Convert statistics format for Spook import
    spook_stats = []
    for stat in statistics_data:
        spook_stat = {"start": stat["start"]}

        # Include available statistic types
        if "sum" in stat:
            spook_stat["sum"] = stat["sum"]
        if "mean" in stat:
            spook_stat["mean"] = stat["mean"]
        if "min" in stat:
            spook_stat["min"] = stat["min"]
        if "max" in stat:
            spook_stat["max"] = stat["max"]
        if "state" in stat:
            spook_stat["state"] = stat["state"]

        spook_stats.append(spook_stat)

    # Process in batches to avoid exceeding HA's 32KB service call limit
    batch_size = 100  # Process 100 statistics entries at a time
    total_imported = 0

    for i in range(0, len(spook_stats), batch_size):
        batch = spook_stats[i : i + batch_size]

        # Build service data for Spook batch
        service_data = {
            "statistic_id": entity_id,
            "source": "recorder",
            "has_mean": any("mean" in stat for stat in statistics_data),
            "has_sum": any("sum" in stat for stat in statistics_data),
            "unit_of_measurement": "kWh",
            "name": entity_entry.name or entity_entry.original_name or entity_id,
            "stats": batch,
        }

        try:
            # Import via Spook
            await hass.services.async_call(
                "recorder", "import_statistics", service_data
            )
            total_imported += len(batch)
            _LOGGER.debug(
                "Imported batch %d-%d (%d entries) for Teslemetry migration %s",
                i + 1,
                i + len(batch),
                len(batch),
                entity_id,
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to import batch %d-%d for Teslemetry migration %s: %s",
                i + 1,
                i + len(batch),
                entity_id,
                e,
            )

    _LOGGER.debug(
        "Imported %d total statistics entries for %s", total_imported, entity_id
    )


async def _trigger_auto_backfill(
    hass: HomeAssistant,
    target_entry: ConfigEntry,
    sensor_prefix: str | None,
    overwrite_existing: bool,
) -> None:
    """Trigger automatic backfill after Teslemetry migration to overwrite with InfluxDB data."""
    try:
        # Get the InfluxDB client from the target entry
        if target_entry.entry_id not in hass.data.get(DOMAIN, {}):
            _LOGGER.warning(
                "Target integration entry %s not found in domain data, cannot trigger auto-backfill",
                target_entry.entry_id,
            )
            return

        store = hass.data[DOMAIN][target_entry.entry_id]
        client: InfluxClient = store.get("client")
        if not client:
            _LOGGER.warning(
                "InfluxDB client not found for entry %s, cannot trigger auto-backfill",
                target_entry.entry_id,
            )
            return

        # Check if InfluxDB has any data at all
        try:
            # Use get_first_timestamp to find earliest available InfluxDB data
            first_timestamp = await hass.async_add_executor_job(
                client.get_first_timestamp
            )
            if not first_timestamp:
                _LOGGER.info(
                    "No InfluxDB data found, skipping auto-backfill (migration data will remain as-is)"
                )
                return

            # Convert to date string for backfill service
            from datetime import datetime
            if isinstance(first_timestamp, str):
                # Parse ISO string to datetime
                first_dt = datetime.fromisoformat(first_timestamp.replace('Z', '+00:00'))
            else:
                first_dt = first_timestamp
            
            start_date_str = first_dt.strftime("%Y-%m-%d")
            
            _LOGGER.info(
                "InfluxDB data available from %s, triggering backfill to overwrite migrated data",
                start_date_str,
            )

            # Create service call data for backfill
            backfill_data = {
                "all": False,
                "start": start_date_str,
                "overwrite_existing": True,  # Always overwrite for auto-backfill
            }
            
            # Add sensor_prefix if specified
            if sensor_prefix:
                backfill_data["sensor_prefix"] = sensor_prefix

            # Create a service call object and trigger backfill
            from homeassistant.core import ServiceCall
            backfill_call = ServiceCall(
                domain=DOMAIN,
                service="backfill",
                data=backfill_data,
                context=None,
                hass=hass,
            )

            _LOGGER.info(
                "AUTO-BACKFILL: Calling backfill service with data: %s",
                backfill_data,
            )
            
            await async_handle_backfill(backfill_call)
            
            _LOGGER.info(
                "=== AUTO-BACKFILL COMPLETE: InfluxDB data has overwritten migrated data where available ==="
            )

        except Exception as e:
            _LOGGER.error(
                "Failed to query InfluxDB for auto-backfill range detection: %s", e
            )
            raise

    except Exception as e:
        _LOGGER.error("Auto-backfill trigger failed: %s", e)
        raise


async def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
    return OptionsFlowHandler(entry)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle migration of config entry data when version changes."""
    version = entry.version or 1

    if version < 2:
        data = {**entry.data}
        if CONF_PW_NAME not in data:
            data[CONF_PW_NAME] = DEFAULT_PW_NAME
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        _LOGGER.info("Migrated config entry %s from v%d to v2", entry.entry_id, version)
        return True

    return True
