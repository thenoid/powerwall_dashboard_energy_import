"""Powerwall Dashboard Energy Import integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    StatisticMetaData,
    async_import_statistics,
)
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.const import UnitOfEnergy
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

    return True


async def async_handle_backfill(call: ServiceCall):  # noqa: C901
    """Handle the service call to backfill historical data."""
    _LOGGER.info("Backfill service called: %s", call.data)
    hass = call.hass

    use_all = call.data.get("all", False)
    start_str = call.data.get("start")
    end_str = call.data.get("end")
    sensor_prefix = call.data.get("sensor_prefix")

    if not use_all and not start_str:
        _LOGGER.error(
            "Backfill service requires either 'all' or 'start' to be specified."
        )
        return

    target_entry: ConfigEntry | None = None
    if sensor_prefix:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_PW_NAME) == sensor_prefix:
                target_entry = entry
                break
        if not target_entry:
            _LOGGER.error(
                "Could not find a Powerwall integration with sensor_prefix: %s",
                sensor_prefix,
            )
            return
    else:
        if len(hass.config_entries.async_entries(DOMAIN)) > 1:
            _LOGGER.warning(
                "Multiple Powerwall integrations found. Using the first one. Specify 'sensor_prefix' to target a specific one."
            )
        target_entry = hass.config_entries.async_entries(DOMAIN)[0]

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

    for sensor_id_suffix, influx_field in BACKFILL_FIELDS.items():
        unique_id = f"{target_entry.entry_id}:powerwall_dashboard_{sensor_id_suffix}"
        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)

        if not entity_id:
            _LOGGER.warning("Could not find entity for unique_id: %s", unique_id)
            continue

        entity_entry = ent_reg.async_get(entity_id)
        if not entity_entry:
            _LOGGER.warning("Could not find entity registry entry for: %s", entity_id)
            continue

        _LOGGER.debug("Processing backfill for %s (%s)", entity_id, influx_field)

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=entity_entry.name or entity_entry.original_name,
            source=DOMAIN,
            statistic_id=entity_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        stats = []
        current_date = start_date
        while current_date <= end_date:
            daily_total = await hass.async_add_executor_job(
                client.get_daily_kwh, influx_field, current_date, series_source
            )

            if daily_total > 0:
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
                        "sum": daily_total,
                    }
                )
            current_date += timedelta(days=1)

        if stats:
            _LOGGER.info("Importing %d statistics for %s", len(stats), entity_id)
            await get_instance(hass).async_add_executor_job(
                async_import_statistics, hass, metadata, stats
            )
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

    return unload_ok


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
