
"""Powerwall Dashboard Energy Import integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN, CONF_HOST, CONF_PORT, CONF_DB_NAME, CONF_USERNAME, CONF_PASSWORD,
    CONF_PW_NAME, DEFAULT_PW_NAME,
)
from .influx_client import InfluxClient
from .metrics import SUPPORTED_METRICS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

BACKFILL_SCHEMA = vol.Schema({
    vol.Optional("start"): cv.datetime,
    vol.Optional("end"): cv.datetime,
    vol.Optional("all", default=False): bool,
    vol.Optional("metrics"): [vol.In(list(SUPPORTED_METRICS.keys()))],
    vol.Optional("dry_run", default=False): bool,
    vol.Optional("chunk_hours", default=168): vol.All(int, vol.Range(min=1, max=24*30)),
})

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    data = entry.data

    client = InfluxClient(
        host=data.get(CONF_HOST, "localhost"),
        port=int(data.get(CONF_PORT, 8086)),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        database=data.get(CONF_DB_NAME, "powerwall"),
    )
    # Connect lazily; diagnostics/history does not require a live server.
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "config": data,
    }

    # Register backfill service on the first setup only
    if DOMAIN not in hass.services.async_services().get(DOMAIN, {}):
        async def _handle_backfill(call: ServiceCall) -> None:
            from .backfill import run_backfill  # local import to avoid hassfest complaints
            await run_backfill(hass, entry, call.data)

        hass.services.async_register(DOMAIN, "backfill", _handle_backfill, schema=BACKFILL_SCHEMA)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    store = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    client = store.get("client") if store else None
    if client:
        client.close()
    return ok

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry versions."""
    version = getattr(entry, "version", 1) or 1
    data = dict(entry.data)

    if version < 2:
        if CONF_PW_NAME not in data:
            data[CONF_PW_NAME] = DEFAULT_PW_NAME
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        _LOGGER.info("Migrated config entry %s from v%d to v2", entry.entry_id, version)
        return True

    return True
