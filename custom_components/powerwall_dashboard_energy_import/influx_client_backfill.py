
from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Optional, Tuple, List

import httpx

_LOGGER = logging.getLogger(__name__)

class InfluxBackfillClient:
    """Minimal async InfluxDB 1.8 client used by backfill."""
    def __init__(self, host: str, port: int, db: str, username: Optional[str]=None, password: Optional[str]=None, timeout: float = 10.0):
        self._base = f"http://{host}:{port}/query"
        self._db = db
        self._auth = (username, password) if username and password else None
        self._timeout = timeout

    async def _q(self, q: str) -> dict:
        params = {"db": self._db, "q": q}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(self._base, params=params, auth=self._auth)
            r.raise_for_status()
            return r.json()

    async def hourly_kwh(self, field: str, start: datetime, end: datetime) -> List[Tuple[datetime, float]]:
        """Return list of (datetime, kWh) for the range, 1h buckets."""
        q = (
            f"SELECT SUM({field}) AS kwh FROM http "
            f"WHERE time >= '{start.astimezone(UTC).isoformat().replace('+00:00','Z')}' "
            f"AND time < '{end.astimezone(UTC).isoformat().replace('+00:00','Z')}' "
            f"GROUP BY time(1h) fill(null)"
        )
        data = await self._q(q)
        out: List[Tuple[datetime, float]] = []
        try:
            values = data["results"][0]["series"][0]["values"]
        except Exception:
            return out
        for ts, kwh in values:
            if kwh is None:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
            out.append((dt, float(kwh)))
        return out
