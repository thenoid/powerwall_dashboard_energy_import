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
    OPT_DAY_MODE,
    OPT_SERIES_SOURCE,
    DEFAULT_DAY_MODE,
    DEFAULT_SERIES_SOURCE,
)
from .influx_client import InfluxClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

# ... truncated for brevity ...
# NOTE: this should contain the patched code as previously built
