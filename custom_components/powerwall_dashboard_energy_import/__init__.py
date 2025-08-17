from .metrics import SUPPORTED_METRICS
from .backfill import run_backfill
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

"""Powerwall Dashboard Energy Import integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN, CONF_HOST, CONF_PORT, CONF_DB_NAME, CONF_USERNAME, CONF_PASSWORD,
    CONF_PW_NAME, DEFAULT_PW_NAME,

from .influx_client import InfluxClient
from .config_flow import OptionsFlowHandler

PLATFORMS: list[str] = ["sensor"]

_LOGGER = logging.getLogger(__name__)

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
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "config": entry.data, "pw_name": pw_name}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async def _handle_backfill(call):
        # Build or reuse client
        conf = entry.data
        client = hass.data.get(DOMAIN, {}).get("client")
        if client is None:
            try:
                from .influx import InfluxClient as _Influx
            except Exception:
                from .influx_client_backfill import InfluxBackfillClient as _Influx
            client = _Influx(
                host=conf.get("host"),
                port=conf.get("port", 8086),
                db=conf.get("database"),
                username=conf.get("username"),
                password=conf.get("password"),
            )

        data = BACKFILL_SCHEMA(call.data)
        result = await run_backfill(
            hass, client,
            metrics=data.get("metrics"),
            start=data.get("start"),
            end=data.get("end"),
            all_mode=data.get("all", False),
            dry_run=data.get("dry_run", False),
            chunk_hours=data.get("chunk_hours", 168),
            statistic_id_prefix=STATISTIC_ID_PREFIX,
        )
        _LOGGER.info("[%s] Backfill result: %s", DOMAIN, result)

    hass.services.async_register(DOMAIN, "backfill", _handle_backfill, schema=BACKFILL_SCHEMA)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        store = hass.data[DOMAIN].pop(entry.entry_id, None)
        if store and (client := store.get("client")):
            await hass.async_add_executor_job(client.close)
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

BACKFILL_SCHEMA = vol.Schema({
    vol.Optional("start"): cv.datetime,
    vol.Optional("end"): cv.datetime,
    vol.Optional("all", default=False): bool,
    vol.Optional("metrics"): [vol.In(list(SUPPORTED_METRICS.keys()))],
    vol.Optional("dry_run", default=False): bool,
    vol.Optional("chunk_hours", default=168): vol.All(int, vol.Range(min=1, max=24*30)),
})
