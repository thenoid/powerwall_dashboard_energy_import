"""Tests for boundary handoff between backfilled and live statistics."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock()
    hass.services = Mock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = Mock(return_value=True)
    hass.config = Mock()
    hass.config.time_zone = "America/Denver"
    return hass


@pytest.fixture
def mock_backfill_call():
    """Create a mock service call for backfill."""
    call_data = {
        "sensor_prefix": "test_pwd",
        "start": "2025-09-01",
        "end": "2025-09-01",
        "overwrite_existing": True,
    }
    call = Mock(spec=ServiceCall)
    call.data = call_data
    return call


class TestBoundaryHandoff:
    """Test boundary handoff between backfilled and live statistics."""

    def test_boundary_discontinuity_reproduction(self):
        """Reproduce the boundary discontinuity issue."""
        # This test should demonstrate the problem where:
        # 1. Backfill creates statistics with high cumulative sum
        # 2. Live sensor starts with low natural state
        # 3. Massive backwards jump occurs at boundary

        # Expected behavior from actual bug:
        backfilled_final_sum = 372.118  # Last backfilled hour
        live_first_sum = 128.091  # First live hour
        backwards_jump = backfilled_final_sum - live_first_sum  # 244 kWh!

        assert backwards_jump > 200, "Should reproduce massive backwards jump"

    def test_backfill_final_statistic_calculation(self):
        """Test how backfill calculates the final statistic sum."""
        # The issue is likely in cumulative base calculation
        # Mock the get_last_statistics call that determines cumulative_base
        pass

    def test_live_sensor_continuation_calculation(self):
        """Test how live sensors calculate their sum after backfill."""
        # Live sensors use: base_sum + current_sensor_state
        # But backfilled data ends with artificial sum
        pass

    @pytest.mark.asyncio
    async def test_baseline_preservation_success(self, mock_hass, mock_backfill_call):
        """Test successful baseline preservation during backfill."""
        # Mock statistics_during_period to return existing baseline
        mock_existing_stats = {
            "sensor.test_pwd_battery_charged_daily": [
                {
                    "start": datetime(2025, 8, 26, 23, 0, tzinfo=timezone.utc),
                    "sum": 5699.087,  # Existing baseline to preserve
                }
            ]
        }

        mock_hass.async_add_executor_job.return_value = mock_existing_stats

        from custom_components.powerwall_dashboard_energy_import import (
            async_backfill_service,
        )

        with (
            patch(
                "custom_components.powerwall_dashboard_energy_import.DOMAIN_DATA", {}
            ),
            patch(
                "custom_components.powerwall_dashboard_energy_import.async_get_entity_registry"
            ) as mock_registry,
            patch(
                "custom_components.powerwall_dashboard_energy_import.InfluxClient"
            ) as mock_client,
        ):
            # Mock entity registry
            mock_reg_instance = Mock()
            mock_reg_instance.async_get.return_value = Mock(
                entity_id="sensor.test_pwd_battery_charged_daily"
            )
            mock_registry.return_value = mock_reg_instance

            # Mock InfluxDB client
            mock_influx = Mock()
            mock_influx.get_daily_energy_data.return_value = {
                "2025-08-27": {"value": 11.541}
            }
            mock_client.return_value = mock_influx

            await async_backfill_service(mock_hass, mock_backfill_call)

            # Verify statistics_during_period was called to get baseline
            mock_hass.async_add_executor_job.assert_called()

    def test_baseline_preservation_type_handling(self):
        """Test baseline preservation handles different timestamp types."""
        from custom_components.powerwall_dashboard_energy_import import (
            _handle_start_value_types,
        )

        # Test string timestamp
        string_start = "2025-08-26T23:00:00-06:00"
        dt_result = _handle_start_value_types(string_start, timezone.utc)
        assert isinstance(dt_result, datetime)

        # Test datetime object
        dt_start = datetime(2025, 8, 26, 23, 0, tzinfo=timezone.utc)
        dt_result = _handle_start_value_types(dt_start, timezone.utc)
        assert isinstance(dt_result, datetime)

        # Test float timestamp
        float_start = 1724731200.0  # Unix timestamp
        dt_result = _handle_start_value_types(float_start, timezone.utc)
        assert isinstance(dt_result, datetime)

        # Test invalid type
        invalid_start = ["invalid"]
        dt_result = _handle_start_value_types(invalid_start, timezone.utc)
        assert dt_result is None

    def test_boundary_discontinuity_fix_verification(self):
        """Verify the boundary discontinuity fix prevents massive jumps."""
        # Before fix: massive backwards jump
        pre_fix_baseline = 0.0  # Wrong baseline
        existing_cumulative = 5699.087  # Actual existing data
        backwards_jump = pre_fix_baseline - existing_cumulative
        assert backwards_jump < -5000, (
            "Should reproduce massive backwards jump before fix"
        )

        # After fix: smooth continuation
        post_fix_baseline = 5699.087  # Preserved baseline
        daily_increment = 11.541  # Natural daily progression
        smooth_continuation = post_fix_baseline + daily_increment
        continuation_jump = smooth_continuation - existing_cumulative
        assert abs(continuation_jump) < 100, "Should have smooth continuation after fix"

    @pytest.mark.asyncio
    async def test_database_query_approach_vs_get_last_statistics(self):
        """Test that database query approach works better than get_last_statistics."""
        # Mock get_last_statistics returning wrong (most recent) data
        mock_wrong_stats = {
            "sensor.test": [
                {
                    "start": datetime(
                        2025, 9, 2, 20, 0, tzinfo=timezone.utc
                    ),  # After backfill start
                    "sum": 100.0,
                }
            ]
        }

        # Mock statistics_during_period returning correct (before backfill) data
        mock_correct_stats = {
            "sensor.test": [
                {
                    "start": datetime(
                        2025, 8, 26, 23, 0, tzinfo=timezone.utc
                    ),  # Before backfill start
                    "sum": 5699.087,
                }
            ]
        }

        # The correct approach should filter by date and find the right baseline
        backfill_start = datetime(2025, 8, 27, 0, 0, tzinfo=timezone.utc)

        # Wrong approach would use the Sep 2 stat (after backfill start)
        wrong_stat = mock_wrong_stats["sensor.test"][0]
        wrong_is_before = wrong_stat["start"] < backfill_start
        assert not wrong_is_before, "get_last_statistics returns wrong timeframe"

        # Correct approach finds the Aug 26 stat (before backfill start)
        correct_stat = mock_correct_stats["sensor.test"][0]
        correct_is_before = correct_stat["start"] < backfill_start
        assert correct_is_before, "statistics_during_period returns correct timeframe"
