
"""InfluxDB client helper for Powerwall Dashboard Energy Import."""
from __future__ import annotations

import logging
from collections import deque
from typing import Any, Optional

try:
    from influxdb import InfluxDBClient  # type: ignore
except Exception:  # pragma: no cover - in CI we don't require InfluxDB installed
    InfluxDBClient = None  # type: ignore

_LOGGER = logging.getLogger(__name__)

class InfluxClient:
    """Wrapper for InfluxDB 1.8.10 queries with history tracking."""

    def __init__(self, host: str, port: int, username: Optional[str], password: Optional[str], database: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self._client = None
        self._history: deque[str] = deque(maxlen=50)

    def connect(self) -> bool:
        if InfluxDBClient is None:
            _LOGGER.debug("InfluxDBClient not available in test environment")
            return True
        try:
            self._client = InfluxDBClient(host=self.host, port=self.port, username=self.username, password=self.password, database=self.database)
            self._client.ping()
            return True
        except Exception as err:  # pragma: no cover
            _LOGGER.error("Failed to connect to InfluxDB: %s", err)
            return False

    def query(self, query: str) -> list[dict[str, Any]]:
        """Run a query and return list of points (dicts)."""
        self._history.append(query)
        if self._client is None:
            # Test mode: return empty
            return []
        try:  # pragma: no cover
            result = self._client.query(query)
            return list(result.get_points()) if result else []
        except Exception as err:
            _LOGGER.error("InfluxDB query failed: %s", err)
            return []

    def get_history(self) -> list[str]:
        """Return a list of recent queries (most recent last)."""
        return list(self._history)

    def close(self) -> None:
        """Close connection."""
        if self._client:  # pragma: no cover
            self._client.close()
            self._client = None
