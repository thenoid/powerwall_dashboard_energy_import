"""Test sensor module comprehensively to achieve >90% coverage."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant

from custom_components.powerwall_dashboard_energy_import.const import (
    DEFAULT_DAY_MODE,
    DEFAULT_SERIES_SOURCE,
    DOMAIN,
)
from custom_components.powerwall_dashboard_energy_import.sensor import (
    SCAN_INTERVAL,
    SENSOR_DEFINITIONS,
    PowerwallDashboardSensor,
    async_setup_entry,
    kwh_defs,
)


class MockInfluxClient:
    """Mock InfluxDB client for testing."""

    def __init__(self, return_data=None):
        self.return_data = return_data or []
        self.query_history = []
        self.query_results = {}

    def query(self, query: str):
        """Mock query method."""
        self.query_history.append(query)

        # Return specific results based on query patterns
        if query in self.query_results:
            return self.query_results[query]

        return self.return_data

    def set_query_result(self, query: str, result: list):
        """Set specific result for a query."""
        self.query_results[query] = result


class TestKwhDefs:
    """Test kwh_defs helper function."""

    def test_kwh_defs_home(self):
        """Test kwh_defs for home usage."""
        result = kwh_defs("home_usage", "home", "mdi:home-lightning-bolt")
        assert len(result) == 3

        # Check total sensor definition
        total_def = result[0]
        assert total_def[0] == "home_usage"
        assert total_def[1] == "Home Usage"
        assert total_def[2] == "home"
        assert total_def[3] == "kwh_total"
        assert total_def[4] == UnitOfEnergy.KILO_WATT_HOUR
        assert total_def[5] == "mdi:home-lightning-bolt"
        assert total_def[6] == SensorDeviceClass.ENERGY
        assert total_def[7] == SensorStateClass.TOTAL_INCREASING

        # Check daily sensor definition
        daily_def = result[1]
        assert daily_def[0] == "home_usage_daily"
        assert daily_def[1] == "Home Usage (Daily)"
        assert daily_def[3] == "kwh_daily"

        # Check monthly sensor definition
        monthly_def = result[2]
        assert monthly_def[0] == "home_usage_monthly"
        assert monthly_def[1] == "Home Usage (Monthly)"
        assert monthly_def[3] == "kwh_monthly"

    def test_kwh_defs_all_fields(self):
        """Test kwh_defs for all supported fields."""
        fields = {
            "home": "Home Usage",
            "solar": "Solar Generated",
            "from_grid": "Grid Imported",
            "to_grid": "Grid Exported",
            "from_pw": "Battery Discharged",
            "to_pw": "Battery Charged",
        }

        for field, expected_name in fields.items():
            result = kwh_defs("test", field, "test-icon")
            assert len(result) == 3
            assert result[0][1] == expected_name
            assert result[1][1] == f"{expected_name} (Daily)"
            assert result[2][1] == f"{expected_name} (Monthly)"


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry(self):
        """Test async_setup_entry creates all sensors."""
        # Create mocks
        hass = Mock(spec=HomeAssistant)
        entry = Mock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.options = {"day_mode": "rolling_24h"}
        async_add_entities = AsyncMock()

        # Mock client and store
        mock_client = MockInfluxClient()
        store = {"client": mock_client, "pw_name": "Test Powerwall"}
        hass.data = {DOMAIN: {"test_entry_id": store}}

        # Call async_setup_entry
        await async_setup_entry(hass, entry, async_add_entities)

        # Verify entities were created
        async_add_entities.assert_called_once()
        entities = async_add_entities.call_args[0][0]

        # Should create one entity for each sensor definition
        assert len(entities) == len(SENSOR_DEFINITIONS)

        # Verify all entities are PowerwallDashboardSensor instances
        for entity in entities:
            assert isinstance(entity, PowerwallDashboardSensor)

    @pytest.mark.asyncio
    async def test_async_setup_entry_default_pw_name(self):
        """Test async_setup_entry with default pw_name."""
        hass = Mock(spec=HomeAssistant)
        entry = Mock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.options = None
        async_add_entities = AsyncMock()

        mock_client = MockInfluxClient()
        store = {"client": mock_client}  # No pw_name
        hass.data = {DOMAIN: {"test_entry_id": store}}

        await async_setup_entry(hass, entry, async_add_entities)

        entities = async_add_entities.call_args[0][0]
        # Verify default name is used
        assert entities[0]._device_name == "Powerwally McPowerwall Face"


class TestPowerwallDashboardSensor:
    """Test PowerwallDashboardSensor class."""

    def create_sensor(self, mode="last_kw", field="solar", options=None, **kwargs):
        """Helper to create a sensor with common defaults."""
        entry = Mock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.options = options or {}

        influx = MockInfluxClient()
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test_entry_id": {}}}

        defaults = {
            "sensor_id": "test_sensor",
            "name": "Test Sensor",
            "unit": UnitOfPower.KILO_WATT,
            "icon": "mdi:test",
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
        }
        defaults.update(kwargs)

        return PowerwallDashboardSensor(
            entry=entry,
            influx=influx,
            options=options or {},
            device_name="Test Device",
            field=field,
            mode=mode,
            hass=hass,
            **defaults,
        )

    def test_sensor_initialization(self):
        """Test sensor initialization with all attributes."""
        entry = Mock(spec=ConfigEntry)
        entry.entry_id = "test_entry"

        influx = MockInfluxClient()
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test_entry": {}}}
        options = {"day_mode": "rolling_24h", "series_source": "raw.http"}

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx,
            options=options,
            device_name="Test Powerwall",
            sensor_id="solar_power",
            name="Solar Power",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            hass=hass,
        )

        # Test all attributes are set correctly
        assert sensor._entry == entry
        assert sensor._influx == influx
        assert sensor._field == "solar"
        assert sensor._mode == "last_kw"
        assert sensor._options == options
        assert sensor._device_name == "Test Powerwall"
        assert sensor._attr_unique_id == "test_entry:powerwall_dashboard_solar_power"
        assert sensor._attr_name == "Solar Power"
        assert sensor._attr_icon == "mdi:solar-power"
        assert sensor._attr_native_unit_of_measurement == UnitOfPower.KILO_WATT
        assert sensor._attr_device_class == SensorDeviceClass.POWER
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT
        assert sensor._attr_native_value is None

        # Test device_info
        expected_device_info = {
            "identifiers": {(DOMAIN, "test_entry")},
            "name": "Test Powerwall",
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }
        assert sensor._attr_device_info == expected_device_info

    def test_series_source_property(self):
        """Test _series_source property method."""
        sensor = self.create_sensor(options={"series_source": "raw.http"})
        assert sensor._series_source() == "raw.http"

        sensor = self.create_sensor(options={})
        assert sensor._series_source() == DEFAULT_SERIES_SOURCE

    def test_day_mode_property(self):
        """Test _day_mode property method."""
        sensor = self.create_sensor(options={"day_mode": "influx_daily_cq"})
        assert sensor._day_mode() == "influx_daily_cq"

        sensor = self.create_sensor(options={})
        assert sensor._day_mode() == DEFAULT_DAY_MODE


class TestSensorUpdateMethods:
    """Test all sensor update modes comprehensively."""

    def test_update_last_kw(self):
        """Test last_kw mode update."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 2500.0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 2.5  # 2500W / 1000 = 2.5kW

    def test_update_last_kw_no_data(self):
        """Test last_kw mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_kw_none_value(self):
        """Test last_kw mode with None value."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_kw_combo_battery(self):
        """Test last_kw_combo_battery mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"chg": 1000, "dis": 2000}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="battery_combo",
            mode="last_kw_combo_battery",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 2.0  # max(1000, 2000) / 1000 = 2.0kW

    def test_update_last_kw_combo_battery_no_data(self):
        """Test last_kw_combo_battery mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="battery_combo",
            mode="last_kw_combo_battery",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_kw_combo_battery_none_values(self):
        """Test last_kw_combo_battery mode with None values."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"chg": None, "dis": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="battery_combo",
            mode="last_kw_combo_battery",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_kw_combo_grid(self):
        """Test last_kw_combo_grid mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"exp": 3000, "imp": 1500}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="grid_combo",
            mode="last_kw_combo_grid",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 3.0  # max(3000, 1500) / 1000 = 3.0kW

    def test_update_last_kw_combo_grid_no_data(self):
        """Test last_kw_combo_grid mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="grid_combo",
            mode="last_kw_combo_grid",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_kw_combo_grid_none_values(self):
        """Test last_kw_combo_grid mode with None values."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"exp": None, "imp": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="grid_combo",
            mode="last_kw_combo_grid",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_last_percentage(self):
        """Test last mode with percentage field."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 87.5}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="percentage",
            mode="last",
            unit=PERCENTAGE,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 87.5

    def test_update_last_percentage_no_data(self):
        """Test last mode with percentage field and no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="percentage",
            mode="last",
            unit=PERCENTAGE,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_state_battery_charging(self):
        """Test state_battery mode when charging."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"charge": 1500, "discharge": 0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="to_pw",
            mode="state_battery",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Charging"

    def test_update_state_battery_discharging(self):
        """Test state_battery mode when discharging."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"charge": 0, "discharge": 2000}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="to_pw",
            mode="state_battery",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Discharging"

    def test_update_state_battery_idle(self):
        """Test state_battery mode when idle."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"charge": 0, "discharge": 0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="to_pw",
            mode="state_battery",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_battery_no_data(self):
        """Test state_battery mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="to_pw",
            mode="state_battery",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_battery_none_values(self):
        """Test state_battery mode with None values."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"charge": None, "discharge": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="to_pw",
            mode="state_battery",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_grid_producing(self):
        """Test state_grid mode when producing (exporting)."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"export": 3000, "import": 0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="from_grid",
            mode="state_grid",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Producing"

    def test_update_state_grid_consuming(self):
        """Test state_grid mode when consuming (importing)."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"export": 0, "import": 2500}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="from_grid",
            mode="state_grid",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Consuming"

    def test_update_state_grid_idle(self):
        """Test state_grid mode when idle."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"export": 0, "import": 0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="from_grid",
            mode="state_grid",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_grid_no_data(self):
        """Test state_grid mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="from_grid",
            mode="state_grid",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_grid_none_values(self):
        """Test state_grid mode with None values."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"export": None, "import": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="from_grid",
            mode="state_grid",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Idle"

    def test_update_state_island_on_grid(self):
        """Test state_island mode when on-grid."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"val": 1}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="ISLAND_GridConnected_bool",
            mode="state_island",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "On-grid"

    def test_update_state_island_off_grid(self):
        """Test state_island mode when off-grid."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"val": 0}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="ISLAND_GridConnected_bool",
            mode="state_island",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Off-grid"

    def test_update_state_island_unknown(self):
        """Test state_island mode when unknown (no data)."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="ISLAND_GridConnected_bool",
            mode="state_island",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Unknown"

    def test_update_state_island_none_value(self):
        """Test state_island mode with None value."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"val": None}]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="ISLAND_GridConnected_bool",
            mode="state_island",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == "Unknown"


class TestSensorKwhModes:
    """Test kwh modes that require datetime mocking."""

    @patch("custom_components.powerwall_dashboard_energy_import.sensor.datetime")
    def test_update_kwh_daily_local_midnight(self, mock_datetime):
        """Test kwh_daily mode with local_midnight day_mode."""
        # Mock current time
        mock_now = datetime(2023, 8, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 12.5}]),
            options={"day_mode": "local_midnight"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_daily",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 12.5

    def test_update_kwh_daily_rolling_24h(self):
        """Test kwh_daily mode with rolling_24h day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 8.3}]),
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_daily",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 8.3

    def test_update_kwh_daily_influx_daily_cq(self):
        """Test kwh_daily mode with influx_daily_cq day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 15.7}]),
            options={"day_mode": "influx_daily_cq"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_daily",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 15.7

    def test_update_kwh_daily_no_data(self):
        """Test kwh_daily mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_daily",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_kwh_daily_with_sum_calculation(self):
        """Test kwh_daily mode with TOTAL_INCREASING state_class sum calculation."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Create a sensor with TOTAL_INCREASING state class to test sum calculation
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 8.25}]),  # Current daily value
            options={"day_mode": "local_midnight"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_daily",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            hass=hass,
        )

        # Mock the _get_existing_baseline method to return a different baseline
        with patch.object(sensor, '_get_existing_baseline', return_value=58.33):
            sensor.update()

        # Check that current daily value is set correctly
        assert sensor._attr_native_value == 8.25
        # Check that sum is set from InfluxDB baseline (lines 438-439)
        assert sensor._attr_sum == 58.33

    @patch("custom_components.powerwall_dashboard_energy_import.sensor.datetime")
    def test_update_kwh_total_local_midnight(self, mock_datetime):
        """Test kwh_total mode with local_midnight day_mode."""
        # Mock current time
        mock_now = datetime(2023, 8, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 42.1}]),
            options={"day_mode": "local_midnight"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 42.1

    def test_update_kwh_total_rolling_24h(self):
        """Test kwh_total mode with rolling_24h day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 33.8}]),
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 33.8

    def test_update_kwh_total_influx_daily_cq(self):
        """Test kwh_total mode with influx_daily_cq day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 27.6}]),
            options={"day_mode": "influx_daily_cq"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 27.6

    def test_update_kwh_total_with_sum_calculation(self):
        """Test kwh_total mode with TOTAL_INCREASING state_class sum calculation."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Create a sensor with TOTAL_INCREASING state class to test sum calculation (lines 438-440)
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 15.5}]),  # Current value
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,  # This triggers sum calculation
            hass=hass,
        )

        # Mock the _get_existing_baseline method to return a known value
        with patch.object(sensor, '_get_existing_baseline', return_value=125.75):
            sensor.update()

        # Check that current value is set correctly
        assert sensor._attr_native_value == 15.5
        # Check that sum is set from InfluxDB baseline (lines 438-439)
        assert sensor._attr_sum == 125.75

    @patch("custom_components.powerwall_dashboard_energy_import.sensor.datetime")
    def test_update_kwh_monthly_integral(self, mock_datetime):
        """Test kwh_monthly mode with integral calculation."""
        # Mock current time
        mock_now = datetime(2023, 8, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 456.7}]),
            options={"day_mode": "local_midnight"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_monthly",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 456.7

    @patch("custom_components.powerwall_dashboard_energy_import.sensor.datetime")
    def test_update_kwh_monthly_influx_daily_cq(self, mock_datetime):
        """Test kwh_monthly mode with influx_daily_cq day_mode."""
        # Mock current time
        mock_now = datetime(2023, 8, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([{"value": 298.4}]),
            options={"day_mode": "influx_daily_cq"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_monthly",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 298.4

    def test_update_kwh_monthly_no_data(self):
        """Test kwh_monthly mode with no data."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_monthly",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value == 0.0

    def test_update_unknown_mode(self):
        """Test unknown mode returns None."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="unknown_mode",
            unit=None,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        sensor.update()
        assert sensor._attr_native_value is None


class TestSensorDefinitions:
    """Test sensor definitions are properly structured."""

    def test_sensor_definitions_structure(self):
        """Test SENSOR_DEFINITIONS has expected structure."""
        assert len(SENSOR_DEFINITIONS) > 0

        for definition in SENSOR_DEFINITIONS:
            assert len(definition) == 8
            sensor_id, name, field, mode, unit, icon, device_class, state_class = (
                definition
            )
            assert isinstance(sensor_id, str)
            assert isinstance(name, str)
            assert isinstance(field, str)
            assert isinstance(mode, str)
            # unit can be None or a unit
            assert isinstance(icon, (str, type(None)))
            # device_class can be None or a device class
            # state_class can be None or a state class

    def test_scan_interval(self):
        """Test SCAN_INTERVAL is set properly."""
        assert SCAN_INTERVAL == timedelta(seconds=60)


class TestSensorBaselineMethod:
    """Test the _get_existing_baseline() method comprehensively."""

    @patch("custom_components.powerwall_dashboard_energy_import.sensor.datetime")
    def test_get_existing_baseline_local_midnight(self, mock_datetime):
        """Test _get_existing_baseline with local_midnight day_mode."""
        # Mock current time
        mock_now = datetime(2023, 8, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Mock InfluxDB client to return baseline value
        influx_client = MockInfluxClient([{"value": 25.123}])

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "local_midnight"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 25.123

    def test_get_existing_baseline_rolling_24h(self):
        """Test _get_existing_baseline with rolling_24h day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Mock InfluxDB client to return baseline value
        influx_client = MockInfluxClient([{"value": 42.567}])

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 42.567

    def test_get_existing_baseline_influx_daily_cq(self):
        """Test _get_existing_baseline with influx_daily_cq day_mode."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Mock InfluxDB client to return baseline value
        influx_client = MockInfluxClient([{"value": 18.999}])

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "influx_daily_cq"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 18.999

    def test_get_existing_baseline_unknown_day_mode(self):
        """Test _get_existing_baseline with unknown day_mode returns 0.0."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        influx_client = MockInfluxClient([])

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "unknown_mode"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 0.0

    def test_get_existing_baseline_no_data(self):
        """Test _get_existing_baseline with no data returns 0.0."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        influx_client = MockInfluxClient([])  # No data

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 0.0

    def test_get_existing_baseline_exception_handling(self):
        """Test _get_existing_baseline handles exceptions gracefully."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}

        # Mock InfluxDB client to raise exception
        influx_client = Mock()
        influx_client.query.side_effect = Exception("Connection error")

        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=influx_client,
            options={"day_mode": "rolling_24h"},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="kwh_total",
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        baseline = sensor._get_existing_baseline()
        assert baseline == 0.0


class TestSensorEdgeCases:
    """Test edge cases and error scenarios."""

    def test_sensor_with_empty_options(self):
        """Test sensor with empty options dict."""
        entry = Mock(entry_id="test")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        # Should use defaults
        assert sensor._series_source() == DEFAULT_SERIES_SOURCE
        assert sensor._day_mode() == DEFAULT_DAY_MODE

    def test_sensor_with_none_options(self):
        """Test sensor with None as options."""
        entry = Mock(entry_id="test", options=None)
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options=None,
            device_name="Test",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        # Should handle None gracefully
        assert sensor._options is None

    def test_device_info_structure(self):
        """Test device_info has correct structure."""
        entry = Mock(entry_id="unique_test_id")
        hass = Mock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"unique_test_id": {}}}
        
        sensor = PowerwallDashboardSensor(
            entry=entry,
            influx=MockInfluxClient([]),
            options={},
            device_name="Custom Device Name",
            sensor_id="test",
            name="Test",
            field="solar",
            mode="last_kw",
            unit=UnitOfPower.KILO_WATT,
            icon=None,
            device_class=None,
            state_class=None,
            hass=hass,
        )

        expected_device_info = {
            "identifiers": {(DOMAIN, "unique_test_id")},
            "name": "Custom Device Name",
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }

        assert sensor._attr_device_info == expected_device_info
