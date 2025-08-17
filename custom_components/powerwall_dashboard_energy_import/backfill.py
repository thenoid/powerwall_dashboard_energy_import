from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder.models.statistics import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

from .const import DOMAIN
from .metrics import SUPPORTED_METRICS, MetricSpec

from __future__ import annotations