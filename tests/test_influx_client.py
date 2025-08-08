
import types
import pytest

from custom_components.powerwall_dashboard_energy_import.influx_client import InfluxClient

class DummyClient:
    def __init__(self):
        self.closed = False
        self.queries = []
    def ping(self): return True
    def query(self, q):
        self.queries.append(q)
        # Return a dummy object with get_points()
        class R:
            def get_points(self_inner):
                return [{"value": 1.234}]
        return R()
    def close(self): self.closed = True

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
