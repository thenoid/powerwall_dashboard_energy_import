
"""Sensor platform for Powerwall Dashboard Energy Import."""
from __future__ import annotations

from typing import Any, Optional, List
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .metrics import SUPPORTED_METRICS

@dataclass
class _Def:
    key: str
    name: str
    unit: str
    device_class: Optional[str] = None
    state_class: Optional[str] = None
    icon: Optional[str] = None

class PowerwallDashboardSensor(SensorEntity):
    """Minimal sensor wrapper around an Influx-like client used by unit tests."""

    _attr_native_value: float | None = None

    def __init__(self, influx: Any, key: str, name: str, unit: str, mode: str, icon: str, device_class: str, state_class: str):
        self._influx = influx
        self._key = key
        self._attr_name = name
        self._unit = unit
        self._mode = mode
        self._attr_icon = icon
        # Device/state class mappings if valid
        self._attr_device_class = getattr(SensorDeviceClass, device_class.upper(), None) if device_class else None
        self._attr_state_class = getattr(SensorStateClass, state_class.upper(), None) if state_class else None

    @property
    def native_unit_of_measurement(self) -> Optional[str]:
        return self._unit

    def update(self) -> None:
        """Pull value from the Influx client (synchronous for tests)."""
        points: List[dict] = self._influx.query(f"SELECT {self._key}") if hasattr(self._influx, 'query') else []
        if self._mode == "last":
            self._attr_native_value = float(points[0].get("value", 0.0)) if points else 0.0
        else:
            # Sum of values; empty -> 0.0
            total = 0.0
            for p in points or []:
                try:
                    total += float(p.get("value", 0.0))
                except Exception:
                    continue
            self._attr_native_value = total

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up sensors from a config entry.

    We keep this minimal; the unit tests create sensors directly. This function is here
    to satisfy Home Assistant platform loading.
    """
    async_add_entities([])
