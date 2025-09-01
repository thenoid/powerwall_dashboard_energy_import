"""Test diagnostics functionality."""

from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

# Import all functions to ensure they're loaded for coverage
from custom_components.powerwall_dashboard_energy_import.const import (
    CONF_DB_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.powerwall_dashboard_energy_import.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


class MockClient:
    """Mock influx client for testing."""

    def __init__(self, history=None):
        self._history = (
            history
            if history is not None
            else ["SELECT * FROM power", "SELECT * FROM energy"]
        )

    def get_history(self):
        """Return query history."""
        return self._history


@pytest.fixture
def mock_hass():
    """Create mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry():
    """Create mock config entry."""
    entry = Mock(spec=ConfigEntry)
    entry.entry_id = "test_entry_id"
    return entry


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_full_data(
    mock_hass, mock_config_entry
):
    """Test diagnostics with full data available."""
    # Set up test data
    client = MockClient()
    config = {
        CONF_HOST: "influx.local",
        CONF_PORT: 8086,
        CONF_DB_NAME: "powerwall",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "secret123",
    }

    # Mock the hass data structure
    mock_hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: {
                "client": client,
                "config": config,
            }
        }
    }

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify the structure and content
    assert "connection" in result
    assert "recent_queries" in result

    # Check connection data
    connection = result["connection"]
    assert connection["host"] == "influx.local"
    assert connection["port"] == 8086
    assert connection["database"] == "powerwall"
    assert connection["username"] == "**REDACTED**"  # Redacted by async_redact_data
    assert connection["password"] == "**REDACTED**"  # Redacted by async_redact_data

    # Check recent queries
    assert result["recent_queries"] == ["SELECT * FROM power", "SELECT * FROM energy"]


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_missing_domain_data(
    mock_hass, mock_config_entry
):
    """Test diagnostics when domain data is missing."""
    # Mock hass with no domain data
    mock_hass.data = {}

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify the structure with empty data
    assert "connection" in result
    assert "recent_queries" in result

    # Check that connection fields are None when config is missing
    connection = result["connection"]
    assert connection["host"] is None
    assert connection["port"] is None
    assert connection["database"] is None
    assert connection["username"] is None  # None values are not redacted
    assert connection["password"] == "**REDACTED**"  # Password is "***" then redacted

    # Check that recent queries is empty when client is missing
    assert result["recent_queries"] == []


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_missing_entry_data(
    mock_hass, mock_config_entry
):
    """Test diagnostics when specific entry data is missing."""
    # Mock hass data with domain but no entry
    mock_hass.data = {DOMAIN: {}}

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify the structure with empty data
    assert "connection" in result
    assert "recent_queries" in result

    # Check that all fields are None/empty when entry is missing
    connection = result["connection"]
    assert connection["host"] is None
    assert connection["port"] is None
    assert connection["database"] is None
    assert connection["username"] is None  # None values are not redacted
    assert connection["password"] == "**REDACTED**"  # Password is "***" then redacted

    assert result["recent_queries"] == []


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_partial_config(
    mock_hass, mock_config_entry
):
    """Test diagnostics with partial config data."""
    # Set up test data with partial config
    client = MockClient(["SELECT 1"])
    config = {
        CONF_HOST: "partial.host",
        # Missing other config fields
    }

    # Mock the hass data structure
    mock_hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: {
                "client": client,
                "config": config,
            }
        }
    }

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify partial data is handled correctly
    connection = result["connection"]
    assert connection["host"] == "partial.host"
    assert connection["port"] is None  # Missing from config
    assert connection["database"] is None  # Missing from config
    assert connection["username"] is None  # None values are not redacted
    assert connection["password"] == "**REDACTED**"  # Password is "***" then redacted

    assert result["recent_queries"] == ["SELECT 1"]


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_no_client(
    mock_hass, mock_config_entry
):
    """Test diagnostics when client is missing but config exists."""
    # Set up test data without client
    config = {
        CONF_HOST: "no-client.host",
        CONF_PORT: 8087,
        CONF_DB_NAME: "test_db",
        CONF_USERNAME: "test_user",
        CONF_PASSWORD: "test_pass",
    }

    # Mock the hass data structure without client
    mock_hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: {
                "config": config,
                # No client
            }
        }
    }

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify config data is present but no queries
    connection = result["connection"]
    assert connection["host"] == "no-client.host"
    assert connection["port"] == 8087
    assert connection["database"] == "test_db"
    assert connection["username"] == "**REDACTED**"  # Redacted by async_redact_data
    assert connection["password"] == "**REDACTED**"  # Redacted by async_redact_data

    # No client means no query history
    assert result["recent_queries"] == []


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_empty_query_history(
    mock_hass, mock_config_entry
):
    """Test diagnostics with client that has empty query history."""
    # Set up test data with client having no history
    client = MockClient([])  # Empty history explicitly
    config = {CONF_HOST: "empty-history.host"}

    # Mock the hass data structure
    mock_hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: {
                "client": client,
                "config": config,
            }
        }
    }

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify empty history is returned correctly
    assert result["recent_queries"] == []


def test_to_redact_constant():
    """Test that TO_REDACT constant contains expected fields."""
    assert CONF_USERNAME in TO_REDACT
    assert CONF_PASSWORD in TO_REDACT
    assert len(TO_REDACT) == 2


@pytest.mark.asyncio
async def test_diagnostics_data_redaction_integration(mock_hass, mock_config_entry):
    """Test that sensitive data is properly redacted by async_redact_data."""
    # Set up test data with sensitive information
    client = MockClient()
    config = {
        CONF_HOST: "redaction.test",
        CONF_USERNAME: "sensitive_user",
        CONF_PASSWORD: "very_secret_password",
    }

    # Mock the hass data structure
    mock_hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: {
                "client": client,
                "config": config,
            }
        }
    }

    # Call the diagnostics function
    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    # Verify that sensitive data is redacted
    # Both username and password should be redacted by async_redact_data
    assert result["connection"]["username"] == "**REDACTED**"
    assert result["connection"]["password"] == "**REDACTED**"

    # Ensure no sensitive data appears anywhere in the result
    result_str = str(result)
    assert "sensitive_user" not in result_str
    assert "very_secret_password" not in result_str

    # Non-sensitive data should remain
    assert result["connection"]["host"] == "redaction.test"
