from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Optional

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

async def run_backfill(
    hass: HomeAssistant,
    client,
    *,
    metrics: Optional[List[str]],
    start: Optional[datetime],
    end: Optional[datetime],
    all_mode: bool,
    dry_run: bool,
    chunk_hours: int,
    statistic_id_prefix: str,
) -> Dict[str, int]:
    selected = _select_metrics(metrics)
    if not selected:
        _LOGGER.warning("[%s] No metrics selected; nothing to do.", DOMAIN)
        return {}

    now = dt_util.utcnow()
    if end is None:
        end = now
    if all_mode:
        firsts = await _earliest_timestamps(hass, client, selected)
        candidates = [ts for ts in firsts.values() if ts is not None]
        if not candidates:
            _LOGGER.warning("[%s] Could not detect earliest timestamps; abort.", DOMAIN)
            return {}
        start = min(candidates)
    if start is None:
        raise ValueError("start is required when all=false")

    start = _floor_hour(dt_util.as_utc(start))
    end = _floor_hour(dt_util.as_utc(end))
    if start >= end:
        _LOGGER.info("[%s] Empty range after normalization; nothing to do.", DOMAIN)
        return {}

    _LOGGER.info(
        "[%s] Backfill range UTC: %s → %s (%d hours), metrics=%s, dry_run=%s",
        DOMAIN, start, end, int((end - start).total_seconds() // 3600),
        [m.name for m in selected], dry_run
    )

    total_written: Dict[str, int] = {}

    for m in selected:
        stat_id = f"{statistic_id_prefix}.{m.statistic_key}"
        meta = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=m.friendly_name,
            source=DOMAIN,
            statistic_id=stat_id,
            unit_of_measurement="kWh",
        )

        last = await hass.async_add_executor_job(
            get_last_statistics, hass, 1, stat_id, True
        )
        base_offset = 0.0
        if last and stat_id in last and last[stat_id]:
            base_offset = last[stat_id][0]["sum"] or 0.0

        written = 0
        for chunk_start in _range_by_hours(start, end, chunk_hours):
            chunk_end = min(end, chunk_start + timedelta(hours=chunk_hours))
            rows = await client.hourly_kwh(m, chunk_start, chunk_end)

            stats: List[StatisticData] = []
            cumulative = base_offset
            for ts, kwh in rows:
                cumulative += float(kwh)
                stats.append(StatisticData(start=ts.replace(tzinfo=timezone.utc), sum=cumulative))

            if not stats:
                continue

            if dry_run:
                _log_preview(m.name, stats)
            else:
                async_add_external_statistics(hass, meta, stats)
                written += len(stats)
                base_offset = stats[-1].sum or base_offset

        total_written[m.name] = written
        _LOGGER.info("[%s] %s: wrote %d hourly rows%s",
                     DOMAIN, m.name, written, " (dry-run)" if dry_run else "")

    return total_written

def _select_metrics(names: Optional[List[str]]) -> List[MetricSpec]:
    if not names:
        return list(SUPPORTED_METRICS.values())
    out = []
    for n in names:
        spec = SUPPORTED_METRICS.get(n)
        if spec:
            out.append(spec)
        else:
            _LOGGER.warning("[%s] Unknown metric '%s' skipped.", DOMAIN, n)
    return out

async def _earliest_timestamps(hass: HomeAssistant, client, metrics: Iterable[MetricSpec]) -> Dict[str, Optional[datetime]]:
    results: Dict[str, Optional[datetime]] = {}
    for m in metrics:
        results[m.name] = await client.first_timestamp(m)
    return results

def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)

def _range_by_hours(start: datetime, end: datetime, step: int):
    cur = start
    while cur < end:
        yield cur
        cur += timedelta(hours=step)

def _log_preview(metric_name: str, stats: List[StatisticData]):
    preview = stats[:5] + (["..."] if len(stats) > 10 else []) + stats[-5:]
    _LOGGER.info("[%s] Preview %s (%d rows): %s", DOMAIN, metric_name, len(stats), preview)
