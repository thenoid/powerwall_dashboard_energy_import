"""Test the config flow for Powerwall Dashboard Energy Import integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.powerwall_dashboard_energy_import.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
)
from custom_components.powerwall_dashboard_energy_import.const import (
    CONF_DB_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PW_NAME,
    CONF_USERNAME,
    DEFAULT_PW_NAME,
    OPT_CQ_TZ,
    OPT_DAY_MODE,
    OPT_SERIES_SOURCE,
)


class TestConfigFlow:
    """Test the config flow."""

    @pytest.mark.asyncio
    async def test_async_step_user_no_input(self):
        """Test async_step_user with no input shows form."""
        flow = ConfigFlow()
        flow.hass = AsyncMock()

        result = await flow.async_step_user()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_async_step_user_valid_input_success(self):
        """Test async_step_user with valid input and successful connection."""
        flow = ConfigFlow()
        flow.hass = AsyncMock()

        valid_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
            CONF_PW_NAME: "My Powerwall",
        }

        # Mock successful connection
        with patch.object(flow, "_async_test_connection", return_value=True):
            result = await flow.async_step_user(valid_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "My Powerwall"
        assert result["data"] == valid_input

    @pytest.mark.asyncio
    async def test_async_step_user_valid_input_default_title(self):
        """Test async_step_user uses default title when pw_name not provided."""
        flow = ConfigFlow()
        flow.hass = AsyncMock()

        minimal_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
            CONF_PW_NAME: DEFAULT_PW_NAME,
        }

        with patch.object(flow, "_async_test_connection", return_value=True):
            result = await flow.async_step_user(minimal_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == DEFAULT_PW_NAME

    @pytest.mark.asyncio
    async def test_async_step_user_connection_failed(self):
        """Test async_step_user with failed connection shows error."""
        flow = ConfigFlow()
        flow.hass = AsyncMock()

        valid_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
            CONF_PW_NAME: "My Powerwall",
        }

        # Mock failed connection
        with patch.object(flow, "_async_test_connection", return_value=False):
            result = await flow.async_step_user(valid_input)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_async_test_connection_success(self):
        """Test _async_test_connection with successful connection."""
        flow = ConfigFlow()
        mock_hass = AsyncMock(spec=HomeAssistant)
        mock_hass.async_add_executor_job = AsyncMock(return_value=True)

        valid_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        }

        # Mock the InfluxClient.connect method to return True
        with patch(
            "custom_components.powerwall_dashboard_energy_import.config_flow.InfluxClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.connect.return_value = True
            mock_client_class.return_value = mock_client

            result = await flow._async_test_connection(mock_hass, valid_input)

            assert result is True
            mock_client_class.assert_called_once_with(
                valid_input[CONF_HOST],
                valid_input[CONF_PORT],
                valid_input.get(CONF_USERNAME),
                valid_input.get(CONF_PASSWORD),
                valid_input[CONF_DB_NAME],
            )
            mock_hass.async_add_executor_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_test_connection_failure(self):
        """Test _async_test_connection with failed connection."""
        flow = ConfigFlow()
        mock_hass = AsyncMock(spec=HomeAssistant)
        mock_hass.async_add_executor_job = AsyncMock(return_value=False)

        valid_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        }

        # Mock the InfluxClient.connect method to return False
        with patch(
            "custom_components.powerwall_dashboard_energy_import.config_flow.InfluxClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.connect.return_value = False
            mock_client_class.return_value = mock_client

            result = await flow._async_test_connection(mock_hass, valid_input)

            assert result is False

    @pytest.mark.asyncio
    async def test_async_test_connection_minimal_input(self):
        """Test _async_test_connection with minimal input (no username/password)."""
        flow = ConfigFlow()
        mock_hass = AsyncMock(spec=HomeAssistant)
        mock_hass.async_add_executor_job = AsyncMock(return_value=True)

        minimal_input = {
            CONF_HOST: "192.168.1.100",
            CONF_PORT: 8086,
            CONF_DB_NAME: "powerwall",
        }

        with patch(
            "custom_components.powerwall_dashboard_energy_import.config_flow.InfluxClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.connect.return_value = True
            mock_client_class.return_value = mock_client

            result = await flow._async_test_connection(mock_hass, minimal_input)

            assert result is True
            mock_client_class.assert_called_once_with(
                minimal_input[CONF_HOST],
                minimal_input[CONF_PORT],
                minimal_input.get(CONF_USERNAME),  # Should be None
                minimal_input.get(CONF_PASSWORD),  # Should be None
                minimal_input[CONF_DB_NAME],
            )


class TestOptionsFlowHandler:
    """Test the options flow handler."""

    def test_init(self):
        """Test OptionsFlowHandler initialization."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {
            OPT_DAY_MODE: "local_midnight",
            OPT_SERIES_SOURCE: "autogen.http",
            OPT_CQ_TZ: "America/New_York",
        }

        handler = OptionsFlowHandler(mock_entry)
        assert handler.entry == mock_entry

    @pytest.mark.asyncio
    async def test_async_step_init(self):
        """Test async_step_init redirects to main step."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        handler = OptionsFlowHandler(mock_entry)

        with patch.object(
            handler, "async_step_main", return_value={"test": "result"}
        ) as mock_main:
            result = await handler.async_step_init({"test": "input"})

            assert result == {"test": "result"}
            mock_main.assert_called_once_with({"test": "input"})

    @pytest.mark.asyncio
    async def test_async_step_main_no_input(self):
        """Test async_step_main with no input shows form with current options."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {
            OPT_DAY_MODE: "local_midnight",
            OPT_SERIES_SOURCE: "autogen.http",
            OPT_CQ_TZ: "America/New_York",
        }

        handler = OptionsFlowHandler(mock_entry)

        result = await handler.async_step_main()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "main"

        # Verify schema has the expected fields
        schema = result["data_schema"].schema
        assert OPT_DAY_MODE in [field.schema for field in schema]
        assert OPT_SERIES_SOURCE in [field.schema for field in schema]
        assert OPT_CQ_TZ in [field.schema for field in schema]

    @pytest.mark.asyncio
    async def test_async_step_main_no_input_default_options(self):
        """Test async_step_main with no input and no existing options uses defaults."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = None

        handler = OptionsFlowHandler(mock_entry)

        result = await handler.async_step_main()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "main"

        # Verify schema has the expected fields
        schema = result["data_schema"].schema
        assert OPT_DAY_MODE in [field.schema for field in schema]
        assert OPT_SERIES_SOURCE in [field.schema for field in schema]
        assert OPT_CQ_TZ in [field.schema for field in schema]

    @pytest.mark.asyncio
    async def test_async_step_main_with_valid_input(self):
        """Test async_step_main with valid input creates entry."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {}

        handler = OptionsFlowHandler(mock_entry)

        user_input = {
            OPT_DAY_MODE: "rolling_24h",
            OPT_SERIES_SOURCE: "raw.http",
            OPT_CQ_TZ: "America/Los_Angeles",
        }

        result = await handler.async_step_main(user_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Options"
        assert result["data"] == user_input

    @pytest.mark.asyncio
    async def test_async_step_main_with_influx_daily_cq(self):
        """Test async_step_main with influx_daily_cq day mode."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {}

        handler = OptionsFlowHandler(mock_entry)

        user_input = {
            OPT_DAY_MODE: "influx_daily_cq",
            OPT_SERIES_SOURCE: "autogen.http",
            OPT_CQ_TZ: "UTC",
        }

        result = await handler.async_step_main(user_input)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Options"
        assert result["data"] == user_input

    @pytest.mark.asyncio
    async def test_async_step_main_validates_day_mode_options(self):
        """Test that the schema validates day_mode options correctly."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {}

        handler = OptionsFlowHandler(mock_entry)

        result = await handler.async_step_main()

        # Find the day_mode field in the schema
        schema = result["data_schema"].schema

        # Check that the expected fields exist in the schema
        field_names = [field.schema for field in schema]
        assert OPT_DAY_MODE in field_names
        assert OPT_SERIES_SOURCE in field_names
        assert OPT_CQ_TZ in field_names

    @pytest.mark.asyncio
    async def test_async_step_main_validates_series_source_options(self):
        """Test that the schema validates series_source options correctly."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {}

        handler = OptionsFlowHandler(mock_entry)

        result = await handler.async_step_main()

        # Find the series_source field in the schema
        schema = result["data_schema"].schema

        # Check that the expected fields exist in the schema
        field_names = [field.schema for field in schema]
        assert OPT_DAY_MODE in field_names
        assert OPT_SERIES_SOURCE in field_names
        assert OPT_CQ_TZ in field_names

    @pytest.mark.asyncio
    async def test_async_step_main_empty_options_uses_defaults(self):
        """Test async_step_main with empty options dict uses defaults."""
        mock_entry = AsyncMock(spec=config_entries.ConfigEntry)
        mock_entry.options = {}

        handler = OptionsFlowHandler(mock_entry)

        result = await handler.async_step_main()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "main"
