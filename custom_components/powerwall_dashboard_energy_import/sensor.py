
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
    DOMAIN, CONF_PW_NAME, DEFAULT_PW_NAME,
    OPT_DAY_MODE, OPT_SERIES_SOURCE,
)
from .influx_client import InfluxClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

def kwh_defs(suffix_base: str, field: str, icon: str):
    name_base = {
        "home": "Home Usage",
        "solar": "Solar Generated",
        "from_grid": "Grid Imported",
        "to_grid": "Grid Exported",
        "from_pw": "Battery Discharged",
        "to_pw": "Battery Charged",
    }[field]
    return [
        (f"{suffix_base}", name_base, field, "kwh_total", UnitOfEnergy.KILO_WATT_HOUR, icon, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
        (f"{suffix_base}_daily", f"{name_base} (Daily)", field, "kwh_daily", UnitOfEnergy.KILO_WATT_HOUR, icon, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
        (f"{suffix_base}_monthly", f"{name_base} (Monthly)", field, "kwh_monthly", UnitOfEnergy.KILO_WATT_HOUR, icon, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL),
    ]

SENSOR_DEFINITIONS = []   + kwh_defs("home_usage", "home", "mdi:home-lightning-bolt")   + kwh_defs("solar_generated", "solar", "mdi:solar-power-variant")   + kwh_defs("grid_imported", "from_grid", "mdi:transmission-tower-import")   + kwh_defs("grid_exported", "to_grid", "mdi:transmission-tower-export")   + kwh_defs("battery_discharged", "from_pw", "mdi:battery-arrow-down")   + kwh_defs("battery_charged", "to_pw", "mdi:battery-arrow-up")   + [
    ("battery_power", "Battery Power", "battery_combo", "last_kw_combo_battery", UnitOfPower.KILO_WATT, "mdi:battery-charging", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("grid_power", "Grid Power", "grid_combo", "last_kw_combo_grid", UnitOfPower.KILO_WATT, "mdi:transmission-tower", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("load_power", "Load Power", "home", "last_kw", UnitOfPower.KILO_WATT, "mdi:home-lightning-bolt", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("solar_power", "Solar Power", "solar", "last_kw", UnitOfPower.KILO_WATT, "mdi:solar-power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    ("percentage_charged", "Battery % Charged", "percentage", "last", PERCENTAGE, "mdi:battery-high", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT),
    ("battery_state", "Tesla Battery State", "to_pw", "state_battery", None, "mdi:battery-heart-variant", None, None),
    ("grid_state", "Tesla Power Grid State", "from_grid", "state_grid", None, "mdi:transmission-tower", None, None),
    ("island_status", "Island Status", "ISLAND_GridConnected_bool", "state_island", None, "mdi:earth", None, None),
  ]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    client: InfluxClient = store["client"]
    # Prefer options name, fall back to data, then default
    pw_name: str = entry.options.get(CONF_PW_NAME) if entry.options else None
    if not pw_name:
        pw_name = entry.data.get(CONF_PW_NAME, DEFAULT_PW_NAME)
    options = entry.options or {}

    entities = []
    for sensor_id, name, field, mode, unit, icon, device_class, state_class in SENSOR_DEFINITIONS:
        entities.append(
            PowerwallDashboardSensor(
                client, options, pw_name, sensor_id, name, field, mode, unit, icon, device_class, state_class
            )
        )
    async_add_entities(entities, True)

class PowerwallDashboardSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, influx: InfluxClient, options: dict, device_name: str, sensor_id: str, name: str, field: str, mode: str, unit, icon: str | None, device_class, state_class) -> None:
        self._influx = influx
        self._field = field
        self._mode = mode
        self._options = options
        self._device_name = device_name

        self._attr_unique_id = f"powerwall_dashboard_{sensor_id}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_value: Any = None

        # Device name set from user-provided Powerwall Name.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "powerwall_dashboard_energy")},
            "name": device_name,
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }

    def _series_source(self) -> str:
        return self._options.get(OPT_SERIES_SOURCE, "autogen.http")

    def _day_mode(self) -> str:
        return self._options.get(OPT_DAY_MODE, "local_midnight")

    def update(self) -> None:
        day_mode = self._day_mode()
        series = self._series_source()

        # Instantaneous power (kW)
        if self._mode == "last_kw":
            pts = self._influx.query(f"SELECT LAST({self._field}) AS value FROM {series}")
            val = pts[0].get('value', 0.0) if pts else 0.0
            self._attr_native_value = round((val or 0.0) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_battery":
            pts = self._influx.query(f"SELECT LAST(to_pw) AS chg, LAST(from_pw) AS dis FROM {series}")
            chg = (pts[0].get("chg") if pts else 0) or 0
            dis = (pts[0].get("dis") if pts else 0) or 0
            self._attr_native_value = round(max(chg, dis) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_grid":
            pts = self._influx.query(f"SELECT LAST(to_grid) AS exp, LAST(from_grid) AS imp FROM {series}")
            exp = (pts[0].get("exp") if pts else 0) or 0
            imp = (pts[0].get("imp") if pts else 0) or 0
            self._attr_native_value = round(max(exp, imp) / 1000.0, 3)
            return

        # Percentage
        if self._mode == "last" and self._field == "percentage":
            pts = self._influx.query(f"SELECT LAST(percentage) AS value FROM {series}")
            self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
            return

        # States
        if self._mode == "state_battery":
            pts = self._influx.query(f"SELECT LAST(to_pw) AS charge, LAST(from_pw) AS discharge FROM {series}")
            chg = (pts[0].get("charge") if pts else 0) or 0
            dis = (pts[0].get("discharge") if pts else 0) or 0
            self._attr_native_value = "Charging" if chg > 0 else ("Discharging" if dis > 0 else "Idle")
            return

        if self._mode == "state_grid":
            pts = self._influx.query(f"SELECT LAST(to_grid) AS export, LAST(from_grid) AS import FROM {series}")
            exp = (pts[0].get("export") if pts else 0) or 0
            imp = (pts[0].get("import") if pts else 0) or 0
            self._attr_native_value = "Producing" if exp > 0 else ("Consuming" if imp > 0 else "Idle")
            return

        if self._mode == "state_island":
            pts = self._influx.query("SELECT LAST(ISLAND_GridConnected_bool) AS val FROM grid.http")
            val = (pts[0].get("val") if pts else None)
            self._attr_native_value = "Unknown" if val is None else ("On-grid" if bool(val) else "Off-grid")
            return

        # kWh general 'today' per options
        if self._mode == "kwh_total":
            if day_mode == "local_midnight":
                midnight_local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                since_iso = midnight_local.astimezone(timezone.utc).isoformat()
                q = f"SELECT integral({self._field})/1000/3600 AS value FROM {series} WHERE time >= '{since_iso}' AND {self._field} > 0"
                pts = self._influx.query(q)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return
            if day_mode == "rolling_24h":
                q = f"SELECT integral({self._field})/1000/3600 AS value FROM {series} WHERE time >= now() - 24h AND {self._field} > 0"
                pts = self._influx.query(q)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return
            if day_mode == "influx_daily_cq":
                pts = self._influx.query("SELECT LAST(%s) AS value FROM daily.http" % self._field)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return

        # kWh baked-in Daily
        if self._mode == "kwh_daily":
            if day_mode == "influx_daily_cq":
                pts = self._influx.query("SELECT LAST(%s) AS value FROM daily.http" % self._field)
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return
            midnight_local = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            since_iso = midnight_local.astimezone(timezone.utc).isoformat()
            q = f"SELECT integral({self._field})/1000/3600 AS value FROM {series} WHERE time >= '{since_iso}' AND {self._field} > 0"
            pts = self._influx.query(q)
            self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
            return

        # kWh baked-in Monthly
        if self._mode == "kwh_monthly":
            if day_mode == "influx_daily_cq":
                now_local = datetime.now().astimezone()
                month_start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                since_iso = month_start_local.astimezone(timezone.utc).isoformat()
                pts = self._influx.query("SELECT SUM(%s) AS value FROM daily.http WHERE time >= '%s'" % (self._field, since_iso))
                self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
                return
            now_local = datetime.now().astimezone()
            month_start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            since_iso = month_start_local.astimezone(timezone.utc).isoformat()
            q = f"SELECT integral({self._field})/1000/3600 AS value FROM {series} WHERE time >= '{since_iso}' AND {self._field} > 0"
            pts = self._influx.query(q)
            self._attr_native_value = round(pts[0].get('value', 0.0), 3) if pts else 0.0
            return

        self._attr_native_value = None
