
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

class PowerwallConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is not None:
            # Try to create a client just to validate input (optional, not connecting in CI)
            return self.async_create_entry(title=user_input.get(CONF_PW_NAME, DEFAULT_PW_NAME), data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=8086): int,
            vol.Required(CONF_DB_NAME, default="powerwall"): str,
            vol.Optional(CONF_USERNAME): str,
            vol.Optional(CONF_PASSWORD): str,
            vol.Optional(CONF_PW_NAME, default=DEFAULT_PW_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_import(self, user_input=None) -> FlowResult:
        # Config entries only; no YAML import
        return self.async_abort(reason="not_supported")


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        return await self.async_step_main(user_input)

    async def async_step_main(self, user_input=None) -> FlowResult:
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
