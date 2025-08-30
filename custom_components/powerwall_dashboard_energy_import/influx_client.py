"""InfluxDB client helper for Powerwall Dashboard Energy Import."""

from __future__ import annotations

import logging
from collections import deque
from datetime import date, timedelta
from typing import Any

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError

_LOGGER = logging.getLogger(__name__)


class InfluxClient:
    """Wrapper for InfluxDB 1.8.10 queries with history tracking."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        database: str,
    ):
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

    def get_first_timestamp(self, series: str) -> str | None:
        """Get the timestamp of the very first record for a series."""
        # We need a field to query, 'home' is a reasonable default for this purpose
        query = f"SELECT FIRST(home) FROM {series}"
        try:
            result = self.query(query)
            if result and "time" in result[0]:
                return result[0]["time"]
        except Exception as err:
            _LOGGER.warning(
                "Could not determine first timestamp for series %s: %s", series, err
            )
        return None

    def get_daily_kwh(self, field: str, day: date, series: str) -> float:
        """Fetch the total kWh for a given field on a specific day."""
        day_start = day.isoformat() + "T00:00:00Z"
        day_end = (day + timedelta(days=1)).isoformat() + "T00:00:00Z"

        query = (
            f"SELECT integral({field})/1000/3600 AS value FROM {series} "
            f"WHERE time >= '{day_start}' AND time < '{day_end}' AND {field} > 0"
        )
        result = self.query(query)
        return round(result[0].get("value", 0.0), 3) if result else 0.0

    def get_hourly_kwh(self, field: str, day: date, series: str) -> list[float]:
        """Fetch hourly kWh values for a given field on a specific day.

        Returns a list of 24 floats representing energy for each hour (0-23).
        This provides realistic energy distribution instead of artificial even splitting.
        """
        day_start = day.isoformat() + "T00:00:00Z"
        day_end = (day + timedelta(days=1)).isoformat() + "T00:00:00Z"

        query = (
            f"SELECT integral({field})/1000/3600 AS value FROM {series} "
            f"WHERE time >= '{day_start}' AND time < '{day_end}' AND {field} > 0 "
            f"GROUP BY time(1h) fill(0)"
        )
        result = self.query(query)

        # Initialize 24-hour array with zeros
        hourly_values = [0.0] * 24

        if result:
            for entry in result:
                if "time" in entry and "value" in entry:
                    # Parse hour from timestamp (e.g., "2025-08-22T14:00:00Z" -> 14)
                    time_str = entry["time"]
                    hour = int(time_str.split("T")[1].split(":")[0])
                    if 0 <= hour < 24:
                        hourly_values[hour] = round(entry.get("value", 0.0), 3)

        return hourly_values

    def get_history(self) -> list[str]:
        """Return a list of recent queries (most recent last)."""
        return list(self._history)

    def close(self):
        """Close connection."""
        if self._client:
            self._client.close()
            self._client = None
