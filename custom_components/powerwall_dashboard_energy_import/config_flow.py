from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST, CONF_PORT, CONF_DB_NAME, CONF_USERNAME, CONF_PASSWORD,
    CONF_PW_NAME, DEFAULT_PW_NAME,
    OPT_DAY_MODE, OPT_SERIES_SOURCE, OPT_CQ_TZ,
    DEFAULT_DAY_MODE, DEFAULT_SERIES_SOURCE, DEFAULT_CQ_TZ,
)
from .influx_client import InfluxClient

BASE_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=8086): int,
    vol.Required(CONF_DB_NAME): str,
    vol.Optional(CONF_USERNAME): str,
    vol.Optional(CONF_PASSWORD): str,
    vol.Required(CONF_PW_NAME, default=DEFAULT_PW_NAME): str,
})

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Powerwall Dashboard Energy Import."""
    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            if not await self._async_test_connection(self.hass, user_input):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=user_input.get(CONF_PW_NAME, DEFAULT_PW_NAME), data=user_input)
        return self.async_show_form(step_id="user", data_schema=BASE_SCHEMA, errors=errors)

    async def _async_test_connection(self, hass: HomeAssistant, data: dict) -> bool:
        client = InfluxClient(
            data[CONF_HOST], data[CONF_PORT], data.get(CONF_USERNAME), data.get(CONF_PASSWORD), data[CONF_DB_NAME]
        )
        return await hass.async_add_executor_job(client.connect)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the integration."""
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        return await self.async_step_main(user_input)

    async def async_step_main(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Options", data=user_input)

        current = self.entry.options or {}
        schema = vol.Schema({
            vol.Required(OPT_DAY_MODE, default=current.get(OPT_DAY_MODE, DEFAULT_DAY_MODE)):
                vol.In(["local_midnight", "rolling_24h", "influx_daily_cq"]),
            vol.Required(OPT_SERIES_SOURCE, default=current.get(OPT_SERIES_SOURCE, DEFAULT_SERIES_SOURCE)):
                vol.In(["autogen.http", "raw.http"]),
            vol.Required(OPT_CQ_TZ, default=current.get(OPT_CQ_TZ, DEFAULT_CQ_TZ)): str,
        })
        return self.async_show_form(step_id="main", data_schema=schema)
