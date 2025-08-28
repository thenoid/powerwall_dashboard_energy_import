"""Powerwall Dashboard Energy Import integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

# Recorder imports removed - we now use Spook's service instead
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

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
    "home_usage_daily": "home",
    "solar_generated_daily": "solar",
    "grid_imported_daily": "from_grid",
    "grid_exported_daily": "to_grid",
    "battery_discharged_daily": "from_pw",
    "battery_charged_daily": "to_pw",
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
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "backfill"):
        hass.services.async_register(DOMAIN, "backfill", async_handle_backfill)

    if not hass.services.has_service(DOMAIN, "migrate_from_teslemetry"):
        hass.services.async_register(
            DOMAIN, "migrate_from_teslemetry", async_handle_teslemetry_migration
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

    _LOGGER.info(
        "Parameters - all: %s, start: %s, end: %s, prefix: %s",
        use_all,
        start_str,
        end_str,
        sensor_prefix,
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
            entry_prefix = entry.data.get(CONF_PW_NAME)
            _LOGGER.info(
                "Checking entry %s with prefix: %s", entry.entry_id, entry_prefix
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
        end_date = (
            datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else date.today()
        )
        if use_all:
            first_ts = await hass.async_add_executor_job(
                client.get_first_timestamp, series_source
            )
            if not first_ts:
                _LOGGER.error("Could not determine the first timestamp from InfluxDB.")
                return
            start_date = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).date()
        else:
            start_date = datetime.strptime(start_str or "", "%Y-%m-%d").date()

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

    for sensor_id_suffix, influx_field in BACKFILL_FIELDS.items():
        _LOGGER.info("Processing sensor: %s -> %s", sensor_id_suffix, influx_field)
        unique_id = f"{target_entry.entry_id}:powerwall_dashboard_{sensor_id_suffix}"
        _LOGGER.info("Looking for unique_id: %s", unique_id)

        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        _LOGGER.info("Found entity_id: %s", entity_id)

        if not entity_id:
            _LOGGER.warning("Could not find entity for unique_id: %s", unique_id)
            continue

        entity_entry = ent_reg.async_get(entity_id)
        if not entity_entry:
            _LOGGER.warning("Could not find entity registry entry for: %s", entity_id)
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

        stats = []
        cumulative_total = 0.0
        current_date = start_date
        while current_date <= end_date:
            daily_total = await hass.async_add_executor_job(
                client.get_daily_kwh, influx_field, current_date, series_source
            )

            if daily_total > 0:
                cumulative_total += daily_total
                stat_start = datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    0,
                    0,
                    0,
                    tzinfo=timezone.utc,
                )
                stats.append(
                    {
                        "start": stat_start,
                        "sum": cumulative_total,
                    }
                )
            current_date += timedelta(days=1)

        if stats:
            _LOGGER.info("Importing %d statistics for %s", len(stats), entity_id)
            _LOGGER.info("Sample stat: %s", stats[0] if stats else "None")

            # Check if Spook's recorder.import_statistics service is available
            if not hass.services.has_service("recorder", "import_statistics"):
                _LOGGER.error(
                    "Backfill requires Spook integration for recorder.import_statistics service. "
                    "Install Spook from https://github.com/frenck/spook or HACS. "
                    "The built-in HA statistics API cannot import data for entities with state_class set."
                )
                continue

            try:
                service_data = {
                    "statistic_id": entity_id,
                    "source": "recorder",
                    "has_mean": False,
                    "has_sum": True,
                    "unit_of_measurement": "kWh",
                    "name": entity_entry.name or entity_entry.original_name,
                    "stats": stats,
                }
                await hass.services.async_call(
                    "recorder", "import_statistics", service_data
                )
                _LOGGER.info(
                    "Successfully imported %d statistics via Spook for %s",
                    len(stats),
                    entity_id,
                )
            except Exception as e:
                _LOGGER.error("Failed to import statistics for %s: %s", entity_id, e)
                _LOGGER.error("Service data was: %s", service_data)
                _LOGGER.error("Stats sample: %s", stats[0] if stats else "None")
        else:
            _LOGGER.info("No new statistics to import for %s", entity_id)


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
    entity_mapping = call.data.get("entity_mapping", {})
    start_date_str = call.data.get("start_date")
    end_date_str = call.data.get("end_date")
    dry_run = call.data.get("dry_run", False)
    overwrite_existing = call.data.get("overwrite_existing", False)
    merge_strategy = call.data.get("merge_strategy", "prioritize_influx")

    _LOGGER.info(
        "Migration parameters - auto_discover: %s, dry_run: %s, merge_strategy: %s",
        auto_discover,
        dry_run,
        merge_strategy,
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
        if start_date_str:
            start_time = (
                datetime.strptime(start_date_str, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .isoformat()
            )
        if end_date_str:
            end_time = (
                datetime.strptime(end_date_str, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .isoformat()
            )

        _LOGGER.info(
            "Migration time range: %s to %s",
            start_time or "beginning",
            end_time or "present",
        )

        # Auto-discover Teslemetry entities if enabled
        teslemetry_entities = {}
        if auto_discover:
            _LOGGER.info("Auto-discovering Teslemetry energy entities...")
            teslemetry_entities = await _discover_teslemetry_entities(hass, ent_reg)
            _LOGGER.info(
                "Found %d potential Teslemetry energy entities",
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

    except Exception as e:
        _LOGGER.error("Migration service failed: %s", e)
        raise


async def _discover_teslemetry_entities(hass: HomeAssistant, ent_reg) -> dict:  # noqa: C901
    """Discover Teslemetry energy entities and map them to our entities."""
    teslemetry_mapping = {}

    # Common Teslemetry entity patterns for energy sensors
    teslemetry_patterns = [
        "home_energy",
        "solar_energy",
        "battery_energy",
        "grid_energy",
        "home_consumption",
        "solar_production",
        "battery_charge",
        "battery_discharge",
        "grid_import",
        "grid_export",
    ]

    our_entity_patterns = {
        "home": "home_usage_daily",
        "solar": "solar_generated_daily",
        "battery_charge": "battery_charged_daily",
        "battery_discharge": "battery_discharged_daily",
        "battery_energy_in": "battery_charged_daily",
        "battery_energy_out": "battery_discharged_daily",
        "grid_import": "grid_imported_daily",
        "grid_export": "grid_exported_daily",
        "grid_energy_in": "grid_imported_daily",
        "grid_energy_out": "grid_exported_daily",
    }

    # Scan entity registry for potential Teslemetry entities
    for entity in ent_reg.entities.values():
        if not entity.entity_id.startswith("sensor."):
            continue

        # Look for Tesla/Teslemetry entities with energy characteristics
        entity_lower = entity.entity_id.lower()
        if "tesla" not in entity_lower and "teslemetry" not in entity_lower:
            continue

        # Check if it's an energy-type entity
        found_pattern = None
        for pattern in teslemetry_patterns:
            if pattern in entity_lower:
                found_pattern = pattern
                break

        if not found_pattern:
            continue

        # Map to our entity format
        our_pattern = None
        for key, value in our_entity_patterns.items():
            if key in found_pattern or key in entity_lower:
                our_pattern = value
                break

        if our_pattern:
            # Find a matching config entry to build our entity ID
            for entry in hass.config_entries.async_entries(DOMAIN):
                our_entity_id = f"sensor.{entry.entry_id.replace('-', '_')}_powerwall_dashboard_{our_pattern}"
                teslemetry_mapping[entity.entity_id] = our_entity_id
                break

    return teslemetry_mapping


async def _extract_teslemetry_statistics(
    hass: HomeAssistant,
    entity_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[dict]:
    """Extract statistics from a Teslemetry entity using recorder.get_statistics."""
    try:
        service_data = {"statistic_ids": [entity_id], "period": "hour"}

        if start_time:
            service_data["start_time"] = start_time
        if end_time:
            service_data["end_time"] = end_time

        # Call recorder.get_statistics service
        response = await hass.services.async_call(
            "recorder",
            "get_statistics",
            service_data,
            blocking=True,
            return_response=True,
        )

        # Extract statistics data
        if response and entity_id in response:
            result = response[entity_id]
            if isinstance(result, list):
                return [stat for stat in result if isinstance(stat, dict)]
            return []
        return []

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
        service_data = {"statistic_ids": [entity_id], "period": "hour"}

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

        return bool(response and entity_id in response and response[entity_id])

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

    # Build service data for Spook
    service_data = {
        "statistic_id": entity_id,
        "source": "recorder",
        "has_mean": any("mean" in stat for stat in statistics_data),
        "has_sum": any("sum" in stat for stat in statistics_data),
        "unit_of_measurement": "kWh",
        "name": entity_entry.name or entity_entry.original_name or entity_id,
        "stats": spook_stats,
    }

    # Import via Spook
    await hass.services.async_call("recorder", "import_statistics", service_data)
    _LOGGER.debug("Imported %d statistics entries for %s", len(spook_stats), entity_id)


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
