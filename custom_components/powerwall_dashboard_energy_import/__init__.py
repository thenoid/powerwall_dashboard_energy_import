"""Powerwall Dashboard Energy Import integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_DB_NAME, CONF_USERNAME, CONF_PASSWORD
from .influx_client import InfluxClient

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

    hass.data[DOMAIN][entry.entry_id] = {"client": client, "config": entry.data}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        store = hass.data[DOMAIN].pop(entry.entry_id, None)
        if store and (client := store.get("client")):
            await hass.async_add_executor_job(client.close)
    return unload_ok
