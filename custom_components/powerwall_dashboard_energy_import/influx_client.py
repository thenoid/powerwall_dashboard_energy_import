"""InfluxDB client helper for Powerwall Dashboard Energy Import."""
from __future__ import annotations

import logging
from collections import deque
from typing import Any
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError

_LOGGER = logging.getLogger(__name__)

class InfluxClient:
    """Wrapper for InfluxDB 1.8.10 queries with history tracking."""

    def __init__(self, host: str, port: int, username: str | None, password: str | None, database: str):
        self.host = host
        self.port = port
        self.username = username or ""
        self.password = password or ""
        self.database = database
        self._client: InfluxDBClient | None = None
        self._history: deque[str] = deque(maxlen=20)  # keep last 20 queries

    def connect(self) -> bool:
        """Establish connection to InfluxDB."""
        try:
            self._client = InfluxDBClient(
                host=self.host,
                port=self.port,
                username=self.username or None,
                password=self.password or None,
                database=self.database,
                timeout=5,
                retries=2,
            )
            self._client.ping()
            _LOGGER.debug("Connected to InfluxDB at %s:%s", self.host, self.port)
            return True
        except (InfluxDBClientError, InfluxDBServerError, ConnectionError) as err:
            _LOGGER.error("InfluxDB connection failed: %s", err)
            return False

    def query(self, query: str) -> list[dict[str, Any]]:
        """Run an InfluxQL query and return the raw result points."""
        if not self._client:
            raise RuntimeError("InfluxDB client not connected")
        _LOGGER.debug("Running InfluxQL: %s", query)
        self._history.append(query)
        try:
            result = self._client.query(query)
            return list(result.get_points()) if result else []
        except Exception as err:
            _LOGGER.error("InfluxDB query failed: %s", err)
            return []

    def get_history(self) -> list[str]:
        """Return a list of recent queries (most recent last)."""
        return list(self._history)

    def close(self):
        """Close connection."""
        if self._client:
            self._client.close()
            self._client = None
