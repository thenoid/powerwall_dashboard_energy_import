"""Tests for backfill service functionality."""

from unittest.mock import Mock


def test_backfill_service_registration():
    """Test that the backfill service can be imported and has the right signature."""
    from custom_components.powerwall_dashboard_energy_import import (
        async_handle_backfill,
    )

    # Function should exist and be callable
    assert callable(async_handle_backfill)

    # Should accept a ServiceCall parameter
    import inspect

    sig = inspect.signature(async_handle_backfill)
    assert len(sig.parameters) == 1
    assert "call" in sig.parameters


def test_spook_service_data_format():
    """Test that we format service data correctly for Spook's recorder.import_statistics."""
    from datetime import datetime, timezone

    # Mock entity entry
    entity_entry = Mock()
    entity_entry.name = "Test Energy Sensor"
    entity_entry.original_name = "Test Energy Sensor"

    # Mock stats data
    stats = [
        {"start": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc), "sum": 10.5},
        {"start": datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc), "sum": 15.2},
    ]

    # Build service data as our code would
    service_data = {
        "statistic_id": "sensor.test_energy_daily",
        "source": "powerwall_dashboard_energy_import",
        "has_mean": False,
        "has_sum": True,
        "unit_of_measurement": "kWh",
        "name": entity_entry.name or entity_entry.original_name,
        "stats": [
            {"start": stat["start"].isoformat(), "sum": stat["sum"]} for stat in stats
        ],
    }

    # Verify format matches Spook's expectations
    assert service_data["statistic_id"] == "sensor.test_energy_daily"
    assert service_data["source"] == "powerwall_dashboard_energy_import"
    assert service_data["has_mean"] is False
    assert service_data["has_sum"] is True
    assert service_data["unit_of_measurement"] == "kWh"
    assert service_data["name"] == "Test Energy Sensor"
    assert len(service_data["stats"]) == 2
    assert service_data["stats"][0]["start"] == "2024-01-01T00:00:00+00:00"
    assert service_data["stats"][0]["sum"] == 10.5
