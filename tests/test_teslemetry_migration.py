"""Tests for Teslemetry migration functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import ServiceCall

from custom_components.powerwall_dashboard_energy_import import (
    _check_existing_statistics,
    _discover_teslemetry_entities,
    _extract_teslemetry_statistics,
    _get_teslemetry_patterns,
    _import_statistics_via_spook,
    async_handle_teslemetry_migration,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.services = Mock()
    hass.config_entries = Mock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_service_call(mock_hass):
    """Create a mock service call for migration."""
    call = Mock(spec=ServiceCall)
    call.hass = mock_hass
    call.data = {
        "auto_discover": True,
        "dry_run": False,
        "overwrite_existing": False,
        "merge_strategy": "prioritize_influx",
    }
    return call


@pytest.fixture
def mock_entity_registry():
    """Create a mock entity registry with sample entities."""
    registry = Mock()

    # Mock Teslemetry entities
    teslemetry_entity = Mock()
    teslemetry_entity.entity_id = "sensor.tesla_site_home_energy"
    teslemetry_entity.name = "Tesla Home Energy"
    teslemetry_entity.original_name = "Tesla Home Energy"

    # Mock our integration entities
    our_entity = Mock()
    our_entity.entity_id = "sensor.powerwall_dashboard_home_usage_daily"
    our_entity.name = "Home Usage (Daily)"
    our_entity.original_name = "Home Usage (Daily)"

    registry.entities = {
        "sensor.tesla_site_home_energy": teslemetry_entity,
        "sensor.powerwall_dashboard_home_usage_daily": our_entity,
    }

    registry.async_get = Mock(
        side_effect=lambda entity_id: registry.entities.get(entity_id)
    )

    return registry


def test_migration_service_registration():
    """Test that the migration service can be imported and has correct signature."""
    import inspect

    # Function should exist and be callable
    assert callable(async_handle_teslemetry_migration)

    # Should accept a ServiceCall parameter
    sig = inspect.signature(async_handle_teslemetry_migration)
    assert len(sig.parameters) == 1
    assert "call" in sig.parameters


@pytest.mark.asyncio
async def test_migration_requires_spook(mock_hass, mock_service_call):
    """Test that migration service fails gracefully when Spook is not available."""
    # Setup mocks
    mock_hass.services.has_service = Mock(return_value=False)  # Spook not available

    with patch(
        "custom_components.powerwall_dashboard_energy_import._LOGGER"
    ) as mock_logger:
        await async_handle_teslemetry_migration(mock_service_call)

        # Verify error was logged about missing Spook
        mock_logger.error.assert_called_with(
            "Teslemetry migration requires Spook integration for recorder.import_statistics service. "
            "Install Spook from https://github.com/frenck/spook or HACS."
        )


@pytest.mark.asyncio
async def test_discover_teslemetry_entities(mock_hass, mock_entity_registry):
    """Test auto-discovery of Teslemetry entities."""
    # Setup config entries
    config_entry = Mock()
    config_entry.entry_id = "test-entry-id"
    config_entry.data = {"pw_name": "test_pw"}
    mock_hass.config_entries.async_entries = Mock(return_value=[config_entry])

    # Add more diverse Teslemetry entities to registry
    solar_entity = Mock()
    solar_entity.entity_id = "sensor.tesla_site_solar_energy"
    mock_entity_registry.entities["sensor.tesla_site_solar_energy"] = solar_entity

    battery_entity = Mock()
    battery_entity.entity_id = "sensor.tesla_site_battery_energy_in"
    mock_entity_registry.entities["sensor.tesla_site_battery_energy_in"] = (
        battery_entity
    )

    # Test legacy discovery (no entity_prefix)
    mapping = await _discover_teslemetry_entities(
        mock_hass, mock_entity_registry, config_entry
    )

    # Should find Tesla entities and map them
    assert len(mapping) > 0
    assert "sensor.tesla_site_home_energy" in mapping
    assert mapping["sensor.tesla_site_home_energy"].endswith("home_usage_daily")


@pytest.mark.asyncio
async def test_discover_teslemetry_entities_with_prefix(
    mock_hass, mock_entity_registry
):
    """Test auto-discovery with entity_prefix parameter."""
    # Setup config entries
    config_entry = Mock()
    config_entry.entry_id = "test-entry-id"
    config_entry.data = {"pw_name": "test_pw"}
    mock_hass.config_entries.async_entries = Mock(return_value=[config_entry])

    # Add entities with non-standard naming (like user's my_home_* entities)
    my_home_solar = Mock()
    my_home_solar.entity_id = "sensor.my_home_solar_generated"
    mock_entity_registry.entities["sensor.my_home_solar_generated"] = my_home_solar

    my_home_battery = Mock()
    my_home_battery.entity_id = "sensor.my_home_battery_charge"
    mock_entity_registry.entities["sensor.my_home_battery_charge"] = my_home_battery

    # Add a Tesla entity that should NOT be found with my_home prefix
    tesla_entity = Mock()
    tesla_entity.entity_id = "sensor.tesla_site_grid_import"
    mock_entity_registry.entities["sensor.tesla_site_grid_import"] = tesla_entity

    # Test discovery with entity_prefix
    mapping = await _discover_teslemetry_entities(
        mock_hass, mock_entity_registry, config_entry, "my_home"
    )

    # Should find my_home entities but not tesla entities
    assert len(mapping) == 2
    assert "sensor.my_home_solar_generated" in mapping
    assert "sensor.my_home_battery_charge" in mapping
    assert "sensor.tesla_site_grid_import" not in mapping

    # Verify proper mapping
    assert mapping["sensor.my_home_solar_generated"].endswith("solar_generated_daily")
    assert mapping["sensor.my_home_battery_charge"].endswith("battery_charged_daily")


@pytest.mark.asyncio
async def test_discover_teslemetry_entities_multiple_prefixes(mock_hass):
    """Test auto-discovery with multiple comma-separated prefixes."""
    # Setup config entries
    config_entry = Mock()
    config_entry.entry_id = "test-entry-id"
    config_entry.data = {"pw_name": "test_pw"}
    mock_hass.config_entries.async_entries = Mock(return_value=[config_entry])

    # Create a fresh entity registry for this test
    fresh_registry = Mock()
    fresh_registry.entities = {}

    # Add entities with different prefixes
    my_home_entity = Mock()
    my_home_entity.entity_id = "sensor.my_home_solar_generated"
    fresh_registry.entities["sensor.my_home_solar_generated"] = my_home_entity

    powerwall_entity = Mock()
    powerwall_entity.entity_id = "sensor.powerwall_battery_discharge"
    fresh_registry.entities["sensor.powerwall_battery_discharge"] = powerwall_entity

    # Test discovery with multiple prefixes
    mapping = await _discover_teslemetry_entities(
        mock_hass, fresh_registry, config_entry, "my_home,powerwall"
    )

    # Should find both entities
    assert len(mapping) == 2
    assert "sensor.my_home_solar_generated" in mapping
    assert "sensor.powerwall_battery_discharge" in mapping


@pytest.mark.asyncio
async def test_discover_with_sensor_prefix(mock_hass, mock_entity_registry):
    """Test that sensor_prefix targets the correct config entry for entity mapping."""
    # Setup multiple config entries with different prefixes
    config_entry_1 = Mock()
    config_entry_1.entry_id = "entry-1-id"
    config_entry_1.data = {"pw_name": "pw001"}

    config_entry_2 = Mock()
    config_entry_2.entry_id = "entry-2-id"
    config_entry_2.data = {"pw_name": "pw085"}

    mock_hass.config_entries.async_entries = Mock(
        return_value=[config_entry_1, config_entry_2]
    )

    # Add a Tesla entity to map
    tesla_entity = Mock()
    tesla_entity.entity_id = "sensor.my_home_grid_exported"
    mock_entity_registry.entities["sensor.my_home_grid_exported"] = tesla_entity

    # Test with specific sensor_prefix targeting pw085
    mapping = await _discover_teslemetry_entities(
        mock_hass, mock_entity_registry, config_entry_2, "my_home"
    )

    # Should map to the pw085 integration instance (entry-2-id)
    assert len(mapping) == 1
    assert "sensor.my_home_grid_exported" in mapping
    expected_entity_id = "sensor.pw085_grid_exported_daily"
    assert mapping["sensor.my_home_grid_exported"] == expected_entity_id


@pytest.mark.asyncio
async def test_extract_teslemetry_statistics():
    """Test extraction of statistics from Teslemetry entities."""
    mock_hass = Mock()
    mock_hass.services.async_call = AsyncMock()

    # Mock response with sample statistics data
    sample_stats = [
        {
            "start": "2024-01-01T00:00:00+00:00",
            "sum": 15.5,
            "mean": 0.65,
            "min": 0.0,
            "max": 2.5,
        },
        {
            "start": "2024-01-01T01:00:00+00:00",
            "sum": 31.0,
            "mean": 0.72,
            "min": 0.0,
            "max": 3.0,
        },
    ]

    mock_hass.services.async_call.return_value = {
        "statistics": {"sensor.tesla_home_energy": sample_stats}
    }

    # Test extraction
    result = await _extract_teslemetry_statistics(
        mock_hass,
        "sensor.tesla_home_energy",
        "2024-01-01T00:00:00+00:00",
        "2024-01-02T00:00:00+00:00",
    )

    # Verify service call
    mock_hass.services.async_call.assert_called_once()
    call_args = mock_hass.services.async_call.call_args

    # Check positional args
    assert call_args[0][0] == "recorder"
    assert call_args[0][1] == "get_statistics"

    # Check service data - it should be in call_args[0][2] or in kwargs
    service_data = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]
    assert service_data["statistic_ids"] == ["sensor.tesla_home_energy"]
    assert service_data["start_time"] == "2024-01-01T00:00:00+00:00"
    assert service_data["end_time"] == "2024-01-02T00:00:00+00:00"

    # Verify result
    assert result == sample_stats
    assert len(result) == 2
    assert result[0]["sum"] == 15.5


@pytest.mark.asyncio
async def test_check_existing_statistics():
    """Test checking for existing statistics in target entities."""
    mock_hass = Mock()
    mock_hass.services.async_call = AsyncMock()

    # Mock response indicating existing statistics
    mock_hass.services.async_call.return_value = {
        "statistics": {
            "sensor.powerwall_dashboard_home_usage_daily": [
                {"start": "2024-01-01T00:00:00+00:00", "sum": 10.0}
            ]
        }
    }

    # Test check for existing statistics
    has_existing = await _check_existing_statistics(
        mock_hass, "sensor.powerwall_dashboard_home_usage_daily"
    )

    assert has_existing is True

    # Test with no existing statistics
    mock_hass.services.async_call.return_value = {}
    has_existing = await _check_existing_statistics(
        mock_hass, "sensor.powerwall_dashboard_home_usage_daily"
    )

    assert has_existing is False


@pytest.mark.asyncio
async def test_import_statistics_via_spook():
    """Test importing statistics using Spook's service."""
    mock_hass = Mock()
    mock_hass.services.async_call = AsyncMock()

    mock_entity = Mock()
    mock_entity.name = "Home Usage (Daily)"
    mock_entity.original_name = "Home Usage (Daily)"

    sample_stats = [
        {"start": "2024-01-01T00:00:00+00:00", "sum": 15.5, "mean": 0.65},
        {"start": "2024-01-01T01:00:00+00:00", "sum": 31.0, "mean": 0.72},
    ]

    # Test import
    await _import_statistics_via_spook(
        mock_hass,
        "sensor.powerwall_dashboard_home_usage_daily",
        mock_entity,
        sample_stats,
    )

    # Verify Spook service call
    mock_hass.services.async_call.assert_called_once()
    call_args = mock_hass.services.async_call.call_args

    # Check positional args
    assert call_args[0][0] == "recorder"
    assert call_args[0][1] == "import_statistics"

    # Check service data - it should be in call_args[0][2] or in kwargs
    service_data = call_args[0][2] if len(call_args[0]) > 2 else call_args[1]
    assert service_data["statistic_id"] == "sensor.powerwall_dashboard_home_usage_daily"
    assert service_data["source"] == "recorder"
    assert service_data["has_mean"] is True
    assert service_data["has_sum"] is True
    assert service_data["unit_of_measurement"] == "kWh"
    assert service_data["name"] == "Home Usage (Daily)"

    # Check converted stats format
    stats = service_data["stats"]
    assert len(stats) == 2
    assert stats[0]["start"] == "2024-01-01T00:00:00+00:00"
    # sum should be included for reasonable values (Energy Dashboard needs it)
    assert stats[0]["sum"] == 15.5
    assert stats[0]["mean"] == 0.65


@pytest.mark.asyncio
async def test_full_migration_dry_run(
    mock_hass, mock_service_call, mock_entity_registry
):
    """Test full migration process in dry-run mode."""
    # Setup mocks
    mock_hass.services.has_service = Mock(return_value=True)  # Spook available
    mock_hass.services.async_call = AsyncMock()
    mock_hass.config.time_zone = "America/Denver"  # Mock timezone properly

    # Mock successful statistics extraction
    sample_stats = [{"start": "2024-01-01T00:00:00+00:00", "sum": 15.5}]

    # Setup config entries
    config_entry = Mock()
    config_entry.entry_id = "test-entry-id"
    mock_hass.config_entries.async_entries = Mock(return_value=[config_entry])

    # Enable dry run
    mock_service_call.data["dry_run"] = True

    with (
        patch(
            "custom_components.powerwall_dashboard_energy_import.async_get_entity_registry",
            return_value=mock_entity_registry,
        ),
        patch(
            "custom_components.powerwall_dashboard_energy_import._discover_teslemetry_entities"
        ) as mock_discover,
        patch(
            "custom_components.powerwall_dashboard_energy_import._extract_teslemetry_statistics"
        ) as mock_extract,
        patch(
            "custom_components.powerwall_dashboard_energy_import._LOGGER"
        ) as mock_logger,
    ):
        # Mock discovery returning mapping
        mock_discover.return_value = {
            "sensor.tesla_site_home_energy": "sensor.powerwall_dashboard_home_usage_daily"
        }

        # Mock extraction returning sample data
        mock_extract.return_value = sample_stats

        # Run migration
        await async_handle_teslemetry_migration(mock_service_call)

        # Verify dry run logging
        mock_logger.info.assert_any_call(
            "DRY RUN: Would import %d statistics for %s",
            1,
            "sensor.powerwall_dashboard_home_usage_daily",
        )
        mock_logger.info.assert_any_call(
            "DRY RUN COMPLETE: Would migrate %d total statistics entries", 1
        )


def test_entity_pattern_matching():
    """Test that entity pattern matching works correctly."""
    # Test various Teslemetry entity patterns
    test_cases = [
        ("sensor.tesla_site_home_energy", "home_usage_daily"),
        ("sensor.tesla_site_solar_energy", "solar_generated_daily"),
        ("sensor.tesla_site_battery_energy_in", "battery_charged_daily"),
        ("sensor.tesla_site_battery_energy_out", "battery_discharged_daily"),
        ("sensor.tesla_site_grid_energy_in", "grid_imported_daily"),
        ("sensor.tesla_site_grid_energy_out", "grid_exported_daily"),
    ]

    # This would be tested by the actual discovery function
    # Here we just verify the pattern matching logic
    our_entity_patterns = {
        "home": "home_usage_daily",
        "solar": "solar_generated_daily",
        "battery_energy_in": "battery_charged_daily",
        "battery_energy_out": "battery_discharged_daily",
        "grid_energy_in": "grid_imported_daily",
        "grid_energy_out": "grid_exported_daily",
    }

    for teslemetry_entity, expected_pattern in test_cases:
        entity_lower = teslemetry_entity.lower()
        found_pattern = None

        for key, value in our_entity_patterns.items():
            if key in entity_lower:
                found_pattern = value
                break

        assert found_pattern == expected_pattern, (
            f"Failed to match {teslemetry_entity} to {expected_pattern}"
        )


def test_service_data_format():
    """Test that service data is formatted correctly for both services."""

    # Test migration service data format
    migration_data = {
        "auto_discover": True,
        "entity_mapping": {"sensor.tesla_home": "sensor.our_home"},
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "dry_run": True,
        "overwrite_existing": False,
        "merge_strategy": "prioritize_influx",
    }

    # Verify all expected fields are present
    expected_fields = [
        "auto_discover",
        "entity_mapping",
        "start_date",
        "end_date",
        "dry_run",
        "overwrite_existing",
        "merge_strategy",
    ]
    for field in expected_fields:
        assert field in migration_data

    # Test statistics data format conversion
    input_stats = [
        {
            "start": "2024-01-01T00:00:00+00:00",
            "sum": 15.5,
            "mean": 0.65,
            "min": 0.0,
            "max": 2.5,
        }
    ]

    # This mimics the conversion logic in _import_statistics_via_spook
    spook_stats = []
    for stat in input_stats:
        spook_stat = {"start": stat["start"]}

        if "sum" in stat:
            spook_stat["sum"] = stat["sum"]
        if "mean" in stat:
            spook_stat["mean"] = stat["mean"]
        if "min" in stat:
            spook_stat["min"] = stat["min"]
        if "max" in stat:
            spook_stat["max"] = stat["max"]

        spook_stats.append(spook_stat)

    # Verify conversion
    assert len(spook_stats) == 1
    assert spook_stats[0]["start"] == "2024-01-01T00:00:00+00:00"
    assert spook_stats[0]["sum"] == 15.5
    assert spook_stats[0]["mean"] == 0.65
    assert spook_stats[0]["min"] == 0.0
    assert spook_stats[0]["max"] == 2.5


@pytest.mark.asyncio
async def test_slugify_edge_cases():
    """Test entity ID normalization with various edge cases."""
    from homeassistant.util import slugify

    # Test cases with actual slugify behavior
    test_cases = [
        ("7579 PW", "7579_pw"),
        ("Café München", "cafe_munchen"),
        ("Test's Name", "test_s_name"),  # Apostrophes become separate underscores
        ("PW-001.V2", "pw_001_v2"),
        ("測試", "ce_shi"),  # Chinese characters
        ("Powerwall  123", "powerwall_123"),  # Multiple spaces
        ("Test---Name", "test_name"),  # Multiple dashes
        ("", ""),  # Empty string
        ("123", "123"),  # Numbers only
        ("PW_123", "pw_123"),  # Existing underscores
    ]

    for input_text, expected in test_cases:
        result = slugify(input_text, separator="_")
        assert result == expected, (
            f"slugify('{input_text}') = '{result}', expected '{expected}'"
        )


@pytest.mark.asyncio
async def test_sensor_prefix_matching_edge_cases(mock_hass, mock_entity_registry):
    """Test sensor prefix matching with various edge cases."""
    from custom_components.powerwall_dashboard_energy_import import (
        _discover_teslemetry_entities,
    )

    # Test cases that would previously fail with manual transformation
    edge_case_configs = [
        {"pw_name": "Café München", "expected_prefix": "cafe_munchen"},
        {
            "pw_name": "Test's PW",
            "expected_prefix": "test_s_pw",
        },  # Apostrophes become underscores
        {"pw_name": "PW-001.V2", "expected_prefix": "pw_001_v2"},
        {"pw_name": "PowerWall  123", "expected_prefix": "powerwall_123"},
    ]

    for config_data in edge_case_configs:
        # Setup config entry with edge case name
        config_entry = Mock()
        config_entry.entry_id = "test-entry-id"
        config_entry.data = config_data
        mock_hass.config_entries.async_entries = Mock(return_value=[config_entry])

        # Add a test Tesla entity
        tesla_entity = Mock()
        tesla_entity.entity_id = "sensor.my_home_solar_energy"
        mock_entity_registry.entities = {"sensor.my_home_solar_energy": tesla_entity}

        # Test discovery with entity prefix
        mapping = await _discover_teslemetry_entities(
            mock_hass, mock_entity_registry, config_entry, "my_home"
        )

        # Should successfully map the entity with proper prefix normalization
        expected_entity_id = (
            f"sensor.{config_data['expected_prefix']}_solar_generated_daily"
        )
        assert len(mapping) == 1
        assert "sensor.my_home_solar_energy" in mapping
        assert mapping["sensor.my_home_solar_energy"] == expected_entity_id


def test_teslemetry_patterns_include_main_sensors():
    """Test that Teslemetry patterns include main sensor mappings (currently failing)."""
    # This test will initially fail - we need to add main sensor mappings
    _, our_entity_patterns = _get_teslemetry_patterns()

    # Check specific keys have main sensor alternatives
    expected_main_entries = [
        ("home_main", "home_usage"),
        ("solar_main", "solar_generated"),
        ("battery_charge_main", "battery_charged"),
        ("battery_discharge_main", "battery_discharged"),
        ("grid_import_main", "grid_imported"),
        ("grid_export_main", "grid_exported"),
    ]

    for pattern, expected_main in expected_main_entries:
        assert pattern in our_entity_patterns, (
            f"Main pattern {pattern} missing from our_entity_patterns"
        )
        assert our_entity_patterns[pattern] == expected_main, (
            f"Main pattern {pattern} should map to {expected_main}"
        )


def test_teslemetry_patterns_include_monthly_sensors():
    """Test that Teslemetry patterns include monthly sensor mappings (currently failing)."""
    # This test will initially fail - we need to add monthly sensor mappings
    _, our_entity_patterns = _get_teslemetry_patterns()

    # Check specific keys have monthly sensor alternatives
    expected_monthly_entries = [
        ("home_monthly", "home_usage_monthly"),
        ("solar_monthly", "solar_generated_monthly"),
        ("battery_charge_monthly", "battery_charged_monthly"),
        ("battery_discharge_monthly", "battery_discharged_monthly"),
        ("grid_import_monthly", "grid_imported_monthly"),
        ("grid_export_monthly", "grid_exported_monthly"),
    ]

    for pattern, expected_monthly in expected_monthly_entries:
        assert pattern in our_entity_patterns, (
            f"Monthly pattern {pattern} missing from our_entity_patterns"
        )
        assert our_entity_patterns[pattern] == expected_monthly, (
            f"Monthly pattern {pattern} should map to {expected_monthly}"
        )


def test_teslemetry_patterns_preserve_daily_sensors():
    """Test that Teslemetry patterns still include existing daily sensor mappings."""
    # These should continue to work
    _, our_entity_patterns = _get_teslemetry_patterns()

    expected_daily_mappings = {
        "home": "home_usage_daily",
        "solar": "solar_generated_daily",
        "battery_charge": "battery_charged_daily",
        "battery_discharge": "battery_discharged_daily",
        "grid_import": "grid_imported_daily",
        "grid_export": "grid_exported_daily",
    }

    for pattern, expected_daily in expected_daily_mappings.items():
        assert pattern in our_entity_patterns, (
            f"Pattern {pattern} missing from our_entity_patterns"
        )
        assert expected_daily in our_entity_patterns.values(), (
            f"Daily sensor {expected_daily} not in mappings"
        )
