
"""Sensor platform for Powerwall Dashboard Energy Import."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .influx_client import InfluxClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

# (entity_id_suffix, Friendly Name, field, unit, mode, icon, device_class, state_class)
SENSOR_DEFINITIONS = [
    # kWh totals (Teslemetry-style since midnight)
    ("battery_charged", "Battery Charged", "to_pw", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:battery-arrow-up", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("battery_discharged", "Battery Discharged", "from_pw", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:battery-arrow-down", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("grid_exported", "Grid Exported", "to_grid", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:transmission-tower-export", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("grid_imported", "Grid Imported", "from_grid", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:transmission-tower-import", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("home_usage", "Home Usage", "home", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:home-lightning-bolt", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("solar_generated", "Solar Generated", "solar", UnitOfEnergy.KILO_WATT_HOUR, "pos", "mdi:solar-power-variant", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    # Instantaneous kW
    ("battery_power", "Battery Power", "to_pw", UnitOfPower.KILO_WATT, "last", "mdi:battery-charging", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("grid_power", "Grid Power", "from_grid", UnitOfPower.KILO_WATT, "last", "mdi:transmission-tower", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("load_power", "Load Power", "home", UnitOfPower.KILO_WATT, "last", "mdi:home-lightning-bolt", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("solar_power", "Solar Power", "solar", UnitOfPower.KILO_WATT, "last", "mdi:solar-power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    # Percentage
    ("percentage_charged", "Battery % Charged", "percentage", PERCENTAGE, "last", "mdi:battery-high", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT),
    # States (no device/state class)
    ("battery_state", "Tesla Battery State", "to_pw", None, "state_battery", "mdi:battery-heart-variant", None, None),
    ("grid_state", "Tesla Power Grid State", "from_grid", None, "state_grid", "mdi:transmission-tower", None, None),
    ("island_status", "Island Status", "ISLAND_GridConnected_bool", None, "state_island", "mdi:earth", None, None),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Powerwall Dashboard Energy Import sensors from a config entry."""
    store = hass.data[DOMAIN][entry.entry_id]
    client: InfluxClient = store["client"]

    entities = []
    for sensor_id, name, field, unit, mode, icon, device_class, state_class in SENSOR_DEFINITIONS:
        entities.append(PowerwallDashboardSensor(client, sensor_id, name, field, unit, mode, icon, device_class, state_class))
    async_add_entities(entities, True)

class PowerwallDashboardSensor(SensorEntity):
    """Representation of a Powerwall Dashboard sensor."""

    _attr_has_entity_name = True

    def __init__(self, influx: InfluxClient, sensor_id: str, name: str, field: str, unit, mode: str, icon: str | None, device_class, state_class) -> None:
        self._influx = influx
        self._field = field
        self._mode = mode

        self._attr_unique_id = f"powerwall_dashboard_{sensor_id}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_value: Any = None

        # Group all sensors under one device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "powerwall_dashboard_energy")},
            "name": "Powerwall Dashboard (InfluxDB)",
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }

    def update(self) -> None:
        """Fetch new state data from InfluxDB."""
        # Midnight in local tz → converted to UTC for InfluxQL
        today_local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc_iso = today_local_midnight.astimezone(timezone.utc).isoformat()

        if self._mode == "pos":  # daily total (kWh) from positive values since midnight
            query = (
                f"SELECT integral({self._field})/1000/3600 AS value "
                f"FROM autogen.http "
                f"WHERE time >= '{midnight_utc_iso}' AND {self._field} > 0"
            )
            points = self._influx.query(query)
            self._attr_native_value = round(points[0]['value'], 3) if points and 'value' in points[0] else 0.0

        elif self._mode == "last":  # latest instantaneous value
            query = f"SELECT LAST({self._field}) AS value FROM autogen.http"
            points = self._influx.query(query)
            self._attr_native_value = round(points[0]['value'], 3) if points and 'value' in points[0] else 0.0

        elif self._mode == "state_battery":
            # Determine state from charging/discharging instantaneous values
            query = "SELECT LAST(to_pw) AS charge, LAST(from_pw) AS discharge FROM autogen.http"
            points = self._influx.query(query)
            chg = (points[0].get("charge") if points else 0) or 0
            dis = (points[0].get("discharge") if points else 0) or 0
            if chg > 0:
                self._attr_native_value = "Charging"
            elif dis > 0:
                self._attr_native_value = "Discharging"
            else:
                self._attr_native_value = "Idle"

        elif self._mode == "state_grid":
            query = "SELECT LAST(to_grid) AS export, LAST(from_grid) AS import FROM autogen.http"
            points = self._influx.query(query)
            exp = (points[0].get("export") if points else 0) or 0
            imp = (points[0].get("import") if points else 0) or 0
            if exp > 0:
                self._attr_native_value = "Producing"
            elif imp > 0:
                self._attr_native_value = "Consuming"
            else:
                self._attr_native_value = "Idle"

        elif self._mode == "state_island":
            # grid connection flag rolled into grid RP via CQ
            query = "SELECT LAST(ISLAND_GridConnected_bool) AS val FROM grid.http"
            points = self._influx.query(query)
            val = (points[0].get("val") if points else None)
            if val is None:
                self._attr_native_value = "Unknown"
            else:
                self._attr_native_value = "On-grid" if bool(val) else "Off-grid"

        else:
            self._attr_native_value = None
