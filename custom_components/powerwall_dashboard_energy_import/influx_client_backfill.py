from __future__ import annotations
from datetime import UTC,datetime,timezone
import logging
import httpx

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class InfluxBackfillClient:
    """Minimal async InfluxDB 1.8 client used by backfill if the main client isn't available."""
    def __init__(self, host: str, port: int, db: str, username: str | None=None, password: str | None=None, timeout: float = 10.0):
        self._base = f"http://{host}:{port}/query"
        self._db = db
        self._auth = (username, password) if username and password else None
        self._timeout = timeout

    async def _q(self, q: str):
        params = {"db": self._db, "q": q}
        async with httpx.AsyncClient(timeout=self._timeout) as s:
            r = await s.get(self._base, params=params, auth=self._auth)
            r.raise_for_status()
            return r.json()

    async def first_timestamp(self, metric) -> datetime | None:
        q = f"SELECT FIRST({metric.field}) FROM http WHERE {metric.field} > 0"
        data = await self._q(q)
        try:
            ts = data["results"][0]["series"][0]["values"][0][0]
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
        except Exception:
            _LOGGER.debug("[%s] earliest timestamp not found for %s", DOMAIN, metric.name)
            return None

    async def hourly_kwh(self, metric, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        q = (
            "SELECT integral({field},1h)/1000 "
            "FROM http "
            "WHERE time >= '{start}' AND time < '{end}' "
            "GROUP BY time(1h) fill(none)"
        ).format(
            field=metric.field,
            start=start.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
            end=end.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        )
        data = await self._q(q)
        out: list[tuple[datetime, float]] = []
        try:
            values = data["results"][0]["series"][0]["values"]
        except Exception:
            return out
        for ts, kwh in values:
            if kwh is None:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=UTC)
            out.append((dt, float(kwh)))
        return out
