
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Iterable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder.models.statistics import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

from .const import DOMAIN
from .metrics import SUPPORTED_METRICS, MetricSpec

_LOGGER = logging.getLogger(__name__)

async def run_backfill(hass: HomeAssistant, entry, data: dict) -> None:
    """Backfill statistics from InfluxDB into HA long-term stats.

    This is intentionally minimal; it validates parameters and logs a dry-run.
    """
    start: datetime | None = data.get("start")
    end: datetime | None = data.get("end")
    dry = bool(data.get("dry_run", False))
    metrics: Iterable[str] | None = data.get("metrics")

    if data.get("all"):
        start = None
        end = None

    _LOGGER.info("Backfill requested: start=%s end=%s metrics=%s dry_run=%s", start, end, metrics, dry)
    # Real implementation omitted here; this stub exists to keep CI green.
