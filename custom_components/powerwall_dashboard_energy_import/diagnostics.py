"""Diagnostics support for Powerwall Dashboard Energy Import."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DB_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DOMAIN,
)

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    """Return diagnostic data for a config entry."""
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    client = store.get("client")
    config = store.get("config", {})

    data = {
        "connection": {
            "host": config.get(CONF_HOST),
            "port": config.get(CONF_PORT),
            "database": config.get(CONF_DB_NAME),
            "username": config.get(CONF_USERNAME),
            "password": "***",  # redacted
        },
        "recent_queries": client.get_history() if client else [],
    }
    return async_redact_data(data, TO_REDACT)
