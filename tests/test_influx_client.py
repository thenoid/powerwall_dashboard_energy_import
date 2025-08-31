from datetime import date

from custom_components.powerwall_dashboard_energy_import.influx_client import (
    InfluxClient,
)


class DummyClient:
    def __init__(self):
        self.closed = False
        self.queries = []

    def ping(self):
        return True

    def query(self, q):
        self.queries.append(q)

        # Return a dummy object with get_points()
        class R:
            def get_points(self_inner):
                return [{"value": 1.234}]

        return R()

    def close(self):
        self.closed = True


class DummyClientHourly:
    """Mock client that returns hourly data for testing."""

    def __init__(self):
        self.closed = False
        self.queries = []

    def ping(self):
        return True

    def query(self, q):
        self.queries.append(q)

        # Return realistic hourly solar data - peak around noon, zero at night
        class R:
            def get_points(self_inner):
                # Mock 24-hour solar generation pattern
                return [
                    {"time": "2025-08-22T00:00:00Z", "value": 0.0},  # midnight
                    {"time": "2025-08-22T01:00:00Z", "value": 0.0},
                    {"time": "2025-08-22T06:00:00Z", "value": 0.5},  # dawn
                    {"time": "2025-08-22T07:00:00Z", "value": 1.2},
                    {"time": "2025-08-22T08:00:00Z", "value": 2.8},
                    {"time": "2025-08-22T09:00:00Z", "value": 4.1},
                    {"time": "2025-08-22T10:00:00Z", "value": 5.6},
                    {"time": "2025-08-22T11:00:00Z", "value": 6.8},
                    {"time": "2025-08-22T12:00:00Z", "value": 7.2},  # peak
                    {"time": "2025-08-22T13:00:00Z", "value": 6.9},
                    {"time": "2025-08-22T14:00:00Z", "value": 5.8},
                    {"time": "2025-08-22T15:00:00Z", "value": 4.5},
                    {"time": "2025-08-22T16:00:00Z", "value": 3.1},
                    {"time": "2025-08-22T17:00:00Z", "value": 1.8},
                    {"time": "2025-08-22T18:00:00Z", "value": 0.4},  # dusk
                    {"time": "2025-08-22T19:00:00Z", "value": 0.0},
                ]

        return R()

    def close(self):
        self.closed = True


def test_history_tracking(monkeypatch):
    ic = InfluxClient("localhost", 8086, None, None, "powerwall")
    # Monkeypatch underlying InfluxDBClient with our dummy
    import custom_components.powerwall_dashboard_energy_import.influx_client as mod

    monkeypatch.setattr(mod, "InfluxDBClient", lambda **kwargs: DummyClient())
    assert ic.connect() is True
    pts = ic.query("SELECT 1")
    assert pts and pts[0]["value"] == 1.234
    history = ic.get_history()
    assert history[-1] == "SELECT 1"
    ic.close()


def test_get_hourly_kwh(monkeypatch):
    """Test that get_hourly_kwh returns realistic hourly solar data."""
    ic = InfluxClient("localhost", 8086, None, None, "powerwall")
    import custom_components.powerwall_dashboard_energy_import.influx_client as mod

    monkeypatch.setattr(mod, "InfluxDBClient", lambda **kwargs: DummyClientHourly())
    assert ic.connect() is True

    # Get hourly data for a test date
    test_date = date(2025, 8, 22)
    hourly_values = ic.get_hourly_kwh("solar", test_date, "autogen.http")

    # Should return 24 values
    assert len(hourly_values) == 24

    # Night hours should be zero
    assert hourly_values[0] == 0.0  # midnight
    assert hourly_values[1] == 0.0  # 1 AM
    assert hourly_values[19] == 0.0  # 7 PM
    assert hourly_values[23] == 0.0  # 11 PM

    # Day hours should have realistic values
    assert hourly_values[6] == 0.5  # 6 AM - dawn
    assert hourly_values[12] == 7.2  # noon - peak
    assert hourly_values[18] == 0.4  # 6 PM - dusk

    # Check query format
    expected_query = (
        "SELECT integral(solar)/1000/3600 AS value FROM autogen.http "
        "WHERE time >= '2025-08-22T00:00:00Z' AND time <= '2025-08-22T23:59:59Z' AND solar > 0 "
        "GROUP BY time(1h) fill(0)"
    )
    assert ic._client.queries[-1] == expected_query

    ic.close()
