"""Sensor platform for Powerwall Dashboard Energy Import."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_DAY_MODE,
    DEFAULT_SERIES_SOURCE,
    DOMAIN,
    OPT_DAY_MODE,
    OPT_SERIES_SOURCE,
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
        (
            f"{suffix_base}",
            name_base,
            field,
            "kwh_total",
            UnitOfEnergy.KILO_WATT_HOUR,
            icon,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            f"{suffix_base}_daily",
            f"{name_base} (Daily)",
            field,
            "kwh_daily",
            UnitOfEnergy.KILO_WATT_HOUR,
            icon,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        ),
        (
            f"{suffix_base}_monthly",
            f"{name_base} (Monthly)",
            field,
            "kwh_monthly",
            UnitOfEnergy.KILO_WATT_HOUR,
            icon,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        ),
    ]


SENSOR_DEFINITIONS = (
    []
    + kwh_defs("home_usage", "home", "mdi:home-lightning-bolt")
    + kwh_defs("solar_generated", "solar", "mdi:solar-power-variant")
    + kwh_defs("grid_imported", "from_grid", "mdi:transmission-tower-import")
    + kwh_defs("grid_exported", "to_grid", "mdi:transmission-tower-export")
    + kwh_defs("battery_discharged", "from_pw", "mdi:battery-arrow-down")
    + kwh_defs("battery_charged", "to_pw", "mdi:battery-arrow-up")
    + [
        (
            "battery_power",
            "Battery Power",
            "battery_combo",
            "last_kw_combo_battery",
            UnitOfPower.KILO_WATT,
            "mdi:battery-charging",
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "grid_power",
            "Grid Power",
            "grid_combo",
            "last_kw_combo_grid",
            UnitOfPower.KILO_WATT,
            "mdi:transmission-tower",
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "load_power",
            "Load Power",
            "home",
            "last_kw",
            UnitOfPower.KILO_WATT,
            "mdi:home-lightning-bolt",
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "solar_power",
            "Solar Power",
            "solar",
            "last_kw",
            UnitOfPower.KILO_WATT,
            "mdi:solar-power",
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "percentage_charged",
            "Battery % Charged",
            "percentage",
            "last",
            PERCENTAGE,
            "mdi:battery-high",
            SensorDeviceClass.BATTERY,
            SensorStateClass.MEASUREMENT,
        ),
        (
            "battery_state",
            "Tesla Battery State",
            "to_pw",
            "state_battery",
            None,
            "mdi:battery-heart-variant",
            None,
            None,
        ),
        (
            "grid_state",
            "Tesla Power Grid State",
            "from_grid",
            "state_grid",
            None,
            "mdi:transmission-tower",
            None,
            None,
        ),
        (
            "island_status",
            "Island Status",
            "ISLAND_GridConnected_bool",
            "state_island",
            None,
            "mdi:earth",
            None,
            None,
        ),
    ]
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors for a config entry."""
    store = hass.data[DOMAIN][entry.entry_id]
    client: InfluxClient = store["client"]
    pw_name: str = store.get("pw_name", "Powerwally McPowerwall Face")
    options: dict[str, Any] = dict(entry.options or {})

    entities: list[PowerwallDashboardSensor] = []
    for (
        sensor_id,
        name,
        field,
        mode,
        unit,
        icon,
        device_class,
        state_class,
    ) in SENSOR_DEFINITIONS:
        entities.append(
            PowerwallDashboardSensor(
                entry,
                client,
                dict(options),
                pw_name,
                sensor_id,
                name,
                field,
                mode,
                unit,
                icon,
                device_class,
                state_class,
                hass,
            )
        )

    async_add_entities(entities, True)


class PowerwallDashboardSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        influx: InfluxClient,
        options: dict,
        device_name: str,
        sensor_id: str,
        name: str,
        field: str,
        mode: str,
        unit,
        icon: str | None,
        device_class,
        state_class,
        hass: HomeAssistant,
    ) -> None:
        self._entry = entry
        self._influx = influx
        self._field = field
        self._mode = mode
        self._options = options
        self._device_name = device_name
        self._hass = hass

        # ---- Unique ID is now namespaced per config entry (fixes collisions) ----
        self._attr_unique_id = f"{entry.entry_id}:powerwall_dashboard_{sensor_id}"

        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_value: Any = None

        # Group entities under a per-entry device to keep registries clean
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": device_name,
            "manufacturer": "Powerwall Dashboard",
            "model": "Influx Importer",
        }

    def _series_source(self) -> str:
        return self._options.get(OPT_SERIES_SOURCE, DEFAULT_SERIES_SOURCE)

    def _day_mode(self) -> str:
        return self._options.get(OPT_DAY_MODE, DEFAULT_DAY_MODE)

    def _get_existing_baseline(self) -> float:
        """Get existing cumulative baseline from statistics to ensure smooth continuation."""
        try:
            entity_id = f"sensor.{(self._attr_unique_id or '').replace(':', '_')}"

            # Get the last statistic to continue from existing baseline
            last_stats = get_last_statistics(self._hass, 1, entity_id, True, {"sum"})

            if last_stats and entity_id in last_stats and last_stats[entity_id]:
                last_stat = last_stats[entity_id][0]
                if "sum" in last_stat and last_stat["sum"] is not None:
                    baseline = float(last_stat["sum"])
                    _LOGGER.debug(
                        "Found existing baseline for %s: %.3f kWh", entity_id, baseline
                    )
                    return baseline

            _LOGGER.debug(
                "No existing baseline found for %s, starting from 0.0", entity_id
            )
            return 0.0

        except Exception as e:
            _LOGGER.warning("Failed to get existing baseline for %s: %s", entity_id, e)
            return 0.0

    def update(self) -> None:  # noqa: C901
        day_mode = self._day_mode()
        series = self._series_source()

        if self._mode == "last_kw":
            pts = self._influx.query(
                f"SELECT LAST({self._field}) AS value FROM {series}"
            )
            val = pts[0].get("value", 0.0) if pts else 0.0
            self._attr_native_value = round((val or 0.0) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_battery":
            pts = self._influx.query(
                f"SELECT LAST(to_pw) AS chg, LAST(from_pw) AS dis FROM {series}"
            )
            chg = (pts[0].get("chg") if pts else 0) or 0
            dis = (pts[0].get("dis") if pts else 0) or 0
            self._attr_native_value = round(max(chg, dis) / 1000.0, 3)
            return

        if self._mode == "last_kw_combo_grid":
            pts = self._influx.query(
                f"SELECT LAST(to_grid) AS exp, LAST(from_grid) AS imp FROM {series}"
            )
            exp = (pts[0].get("exp") if pts else 0) or 0
            imp = (pts[0].get("imp") if pts else 0) or 0
            self._attr_native_value = round(max(exp, imp) / 1000.0, 3)
            return

        if self._mode == "last" and self._field == "percentage":
            pts = self._influx.query(f"SELECT LAST(percentage) AS value FROM {series}")
            self._attr_native_value = round(pts[0].get("value", 0.0), 3) if pts else 0.0
            return

        if self._mode == "state_battery":
            pts = self._influx.query(
                f"SELECT LAST(to_pw) AS charge, LAST(from_pw) AS discharge FROM {series}"
            )
            chg = (pts[0].get("charge") if pts else 0) or 0
            dis = (pts[0].get("discharge") if pts else 0) or 0
            self._attr_native_value = (
                "Charging" if chg > 0 else ("Discharging" if dis > 0 else "Idle")
            )
            return

        if self._mode == "state_grid":
            pts = self._influx.query(
                f"SELECT LAST(to_grid) AS export, LAST(from_grid) AS import FROM {series}"
            )
            exp = (pts[0].get("export") if pts else 0) or 0
            imp = (pts[0].get("import") if pts else 0) or 0
            self._attr_native_value = (
                "Producing" if exp > 0 else ("Consuming" if imp > 0 else "Idle")
            )
            return

        if self._mode == "state_island":
            pts = self._influx.query(
                "SELECT LAST(ISLAND_GridConnected_bool) AS val FROM grid.http"
            )
            val = pts[0].get("val") if pts else None
            self._attr_native_value = (
                "Unknown" if val is None else ("On-grid" if bool(val) else "Off-grid")
            )
            return

        if self._mode in ("kwh_total", "kwh_daily"):
            # For TOTAL_INCREASING sensors, we need both native_value and sum
            current_value = 0.0

            if day_mode == "local_midnight":
                midnight_local = (
                    datetime.now()
                    .astimezone()
                    .replace(hour=0, minute=0, second=0, microsecond=0)
                )
                since_iso = midnight_local.astimezone(timezone.utc).isoformat()
                q = (
                    f"SELECT integral({self._field})/1000/3600 AS value FROM {series} "
                    f"WHERE time >= '{since_iso}' AND {self._field} > 0"
                )
                pts = self._influx.query(q)
                current_value = round(pts[0].get("value", 0.0), 3) if pts else 0.0

            elif day_mode == "rolling_24h":
                q = (
                    f"SELECT integral({self._field})/1000/3600 AS value FROM {series} "
                    f"WHERE time >= now() - 24h AND {self._field} > 0"
                )
                pts = self._influx.query(q)
                current_value = round(pts[0].get("value", 0.0), 3) if pts else 0.0

            elif day_mode == "influx_daily_cq":
                pts = self._influx.query(
                    f"SELECT LAST({self._field}) AS value FROM daily.http"
                )
                current_value = round(pts[0].get("value", 0.0), 3) if pts else 0.0

            # Set the current sensor reading
            self._attr_native_value = current_value

            # For TOTAL_INCREASING sensors, calculate cumulative sum with baseline coordination
            if self._attr_state_class == SensorStateClass.TOTAL_INCREASING:
                existing_baseline = self._get_existing_baseline()
                self._attr_sum = existing_baseline + current_value
                _LOGGER.debug(
                    "Sensor %s: baseline=%.3f + current=%.3f = sum=%.3f",
                    self._attr_unique_id,
                    existing_baseline,
                    current_value,
                    self._attr_sum,
                )

            return

        if self._mode == "kwh_monthly":
            now_local = datetime.now().astimezone()
            month_start_local = now_local.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            since_iso = month_start_local.astimezone(timezone.utc).isoformat()

            if day_mode == "influx_daily_cq":
                pts = self._influx.query(
                    f"SELECT SUM({self._field}) AS value FROM daily.http WHERE time >= '{since_iso}'"
                )
                self._attr_native_value = (
                    round(pts[0].get("value", 0.0), 3) if pts else 0.0
                )
                return

            q = (
                f"SELECT integral({self._field})/1000/3600 AS value FROM {series} "
                f"WHERE time >= '{since_iso}' AND {self._field} > 0"
            )
            pts = self._influx.query(q)
            self._attr_native_value = round(pts[0].get("value", 0.0), 3) if pts else 0.0
            return

        self._attr_native_value = None
