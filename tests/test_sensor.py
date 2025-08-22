from unittest.mock import Mock

from custom_components.powerwall_dashboard_energy_import.sensor import (
    PowerwallDashboardSensor,
)


class DummyInflux:
    def __init__(self, points):
        self._points = points
        self._history = []

    def query(self, q):
        self._history.append(q)
        return self._points


def test_sensor_last_value(monkeypatch):
    influx = DummyInflux([{"value": 2500.0}])  # 2500W = 2.5kW after /1000 conversion
    entry = Mock()
    s = PowerwallDashboardSensor(
        entry,
        influx,
        {},
        "Test Device",
        "solar_power",
        "Solar Power",
        "solar",
        "last_kw",
        "kW",
        "mdi:solar-power",
        "power",
        "measurement",
    )
    s.update()
    assert float(s.native_value) == 2.5


def test_sensor_integral_zero(monkeypatch):
    influx = DummyInflux([])  # no points
    entry = Mock()
    s = PowerwallDashboardSensor(
        entry,
        influx,
        {},
        "Test Device",
        "solar_generated",
        "Solar Generated",
        "solar",
        "kwh_daily",
        "kWh",
        "mdi:solar-power",
        "energy",
        "total",
    )
    s.update()
    assert float(s.native_value) == 0.0
