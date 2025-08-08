
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
from homeassistant.const import UnitOfPower, UnitOfEnergy, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    OPT_DAY_MODE, OPT_SERIES_SOURCE, OPT_CQ_TZ,
    DEFAULT_DAY_MODE, DEFAULT_SERIES_SOURCE, DEFAULT_CQ_TZ,
)

from .influx_client import InfluxClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

# (entity_id_suffix, Friendly Name, field, mode, unit, icon, device_class, state_class)
SENSOR_DEFINITIONS = [
    # kWh totals (Teslemetry-style since midnight)
    ("battery_charged", "Battery Charged", "to_pw", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery-arrow-up", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("battery_discharged", "Battery Discharged", "from_pw", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery-arrow-down", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("grid_exported", "Grid Exported", "to_grid", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:transmission-tower-export", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("grid_imported", "Grid Imported", "from_grid", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:transmission-tower-import", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("home_usage", "Home Usage", "home", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:home-lightning-bolt", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ("solar_generated", "Solar Generated", "solar", "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, "mdi:solar-power-variant", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    # Instantaneous kW
    ("battery_power", "Battery Power", "battery_combo", "last_kw_combo_battery", UnitOfPower.KILO_WATT, "mdi:battery-charging", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("grid_power", "Grid Power", "grid_combo", "last_kw_combo_grid", UnitOfPower.KILO_WATT, "mdi:transmission-tower", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("load_power", "Load Power", "home", "last_kw", UnitOfPower.KILO_WATT, "mdi:home-lightning-bolt", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("solar_power", "Solar Power", "solar", "last_kw", UnitOfPower.KILO_WATT, "mdi:solar-power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    # Percentage
    ("percentage_charged", "Battery % Charged", "percentage", "last", PERCENTAGE, "mdi:battery-high", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT),
    # States (no device/state class)
    ("battery_state", "Tesla Battery State", "to_pw", "state_battery", None, "mdi:battery-heart-variant", None, None),
    ("grid_state", "Tesla Power Grid State", "from_grid", "state_grid", None, "mdi:transmission-tower", None, None),
    ("island_status", "Island Status", "ISLAND_GridConnected_bool", "state_island", None, "mdi:earth", None, None),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    client: InfluxClient = store["client"]
    options = entry.options or {}

    entities = []
    for sensor_id, name, field, mode, unit, icon, device_class, state_class in SENSOR_DEFINITIONS:
        entities.append(
            PowerwallDashboardSensor(
                client, options, sensor_id, name, field, mode, unit, icon, device_class, state_class
            )
        )
    async_add_entities(entities, True)

class PowerwallDashboardSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, influx: InfluxClient, options: dict, sensor_id: str, name: str, field: str, mode: str, unit, icon: str | None, device_class, state_class) -> None:
        self._influx = influx
        self._field = field
        self._mode = mode
        self._options = options

        self._attr_unique_id = f"powerwall_dashboard_{sensor_id}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_value: Any = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, "powerwall_dashboard_energy")},
            "name": "Powerwall Dashboard (InfluxDB)",
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }

    def _series_source(self) -> str:
        return self._options.get(OPT_SERIES_SOURCE, DEFAULT_SERIES_SOURCE)

    def _day_mode(self) -> str:
        return self._options.get(OPT_DAY_MODE, DEFAULT_DAY_MODE)

    def _cq_tz(self) -> str:
        return self._options.get(OPT_CQ_TZ, DEFAULT_CQ_TZ)

    def update(self) -> None:
        day_mode = self._day_mode()
        series = self._series_source()

        # Instantaneous power logic (kW) unaffected by options
        if self._mode == "last_kw":
            query = f"SELECT LAST({self._field}) AS value FROM {series}"
            pts = self._influx.query(query)
            val = pts[0].get('value', 0.0) if pts else 0.0
            self._attr_native_value = round((val or 0.0) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_battery":
            query = f"SELECT LAST(to_pw) AS chg, LAST(from_pw) AS dis FROM {series}"
            pts = self._influx.query(query)
            chg = (pts[0].get("chg") if pts else 0) or 0
            dis = (pts[0].get("dis") if pts else 0) or 0
            self._attr_native_value = round(max(chg, dis) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_grid":
            query = f"SELECT LAST(to_grid) AS exp, LAST(from_grid) AS imp FROM {series}"
            pts = self._influx.query(query)
            exp = (pts[0].get("exp") if pts else 0) or 0
            imp = (pts[0].get("imp") if pts else 0) or 0
            self._attr_native_value = round(max(exp, imp) / 1000.0, 3)
            return

        # Percentage
        if self._mode == "last" and self._field == "percentage":
            query = f"SELECT LAST(percentage) AS value FROM {series}"
            pts = self._influx.query(query)
            self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
            return

        # States
        if self._mode == "state_battery":
            query = f"SELECT LAST(to_pw) AS charge, LAST(from_pw) AS discharge FROM {series}"
            pts = self._influx.query(query)
            chg = (pts[0].get("charge") if pts else 0) or 0
            dis = (pts[0].get("discharge") if pts else 0) or 0
            self._attr_native_value = "Charging" if chg > 0 else ("Discharging" if dis > 0 else "Idle")
            return

        if self._mode == "state_grid":
            query = f"SELECT LAST(to_grid) AS export, LAST(from_grid) AS import FROM {series}"
            pts = self._influx.query(query)
            exp = (pts[0].get("export") if pts else 0) or 0
            imp = (pts[0].get("import") if pts else 0) or 0
            self._attr_native_value = "Producing" if exp > 0 else ("Consuming" if imp > 0 else "Idle")
            return

        if self._mode == "state_island":
            # Island flag is maintained by a CQ in the 'grid' RP
            query = "SELECT LAST(ISLAND_GridConnected_bool) AS val FROM grid.http"
            pts = self._influx.query(query)
            val = (pts[0].get("val") if pts else None)
            self._attr_native_value = "Unknown" if val is None else ("On-grid" if bool(val) else "Off-grid")
            return

        # kWh totals with selectable day boundary/source
        if self._mode == "kwh_total":
            if day_mode == "local_midnight":
                midnight_local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                since_iso = midnight_local.astimezone(timezone.utc).isoformat()
                query = (
                    f"SELECT integral({self._field})/1000/3600 AS value FROM {series} "
                    f"WHERE time >= '{since_iso}' AND {self._field} > 0"
                )
                pts = self._influx.query(query)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return

            if day_mode == "rolling_24h":
                query = (
                    f"SELECT integral({self._field})/1000/3600 AS value FROM {series} "
                    f"WHERE time >= now() - 24h AND {self._field} > 0"
                )
                pts = self._influx.query(query)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return

            if day_mode == "influx_daily_cq":
                # Use pre-aggregated daily sum from RP 'daily' (CQ already applies TZ)
                # We'll fetch LAST() for today.
                query = "SELECT LAST(%s) AS value FROM daily.http" % self._field
                pts = self._influx.query(query)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return

        # If nothing matched
        self._attr_native_value = None
