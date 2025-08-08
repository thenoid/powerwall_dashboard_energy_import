"""Config flow for Powerwall Dashboard Energy Import integration."""

from __future__ import annotations
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_DB_NAME, CONF_USERNAME, CONF_PASSWORD

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=8086): int,
    vol.Required(CONF_DB_NAME): str,
    vol.Optional(CONF_USERNAME): str,
    vol.Optional(CONF_PASSWORD): str,
})

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Powerwall Dashboard Energy Import."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # TODO: Validate InfluxDB connection here
            return self.async_create_entry(title="Powerwall Dashboard Energy Import", data=user_input)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
