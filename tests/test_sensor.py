
import datetime as dt
from custom_components.powerwall_dashboard_energy_import.sensor import PowerwallDashboardSensor

class DummyInflux:
    def __init__(self, points):
        self._points = points
        self._history = []
    def query(self, q):
        self._history.append(q)
        return self._points

def test_sensor_last_value(monkeypatch):
    influx = DummyInflux([{"value": 2.5}])
    s = PowerwallDashboardSensor(influx, "solar_power", "Solar Power", "solar", "kW", "last", "mdi:solar-power", "power", "measurement")
    s.update()
    assert float(s.native_value) == 2.5

def test_sensor_integral_zero(monkeypatch):
    influx = DummyInflux([])  # no points
    s = PowerwallDashboardSensor(influx, "solar_generated", "Solar Generated", "solar", "kWh", "pos", "mdi:solar-power", "energy", "total")
    s.update()
    assert float(s.native_value) == 0.0
