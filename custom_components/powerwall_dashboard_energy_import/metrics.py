from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    name: str
    field: str
    statistic_key: str
    friendly_name: str

SUPPORTED_METRICS: dict[str, MetricSpec] = {
    # Grid
    "grid_import":        MetricSpec("grid_import", "from_grid", "grid_import", "Grid Imported"),
    "grid_export":        MetricSpec("grid_export", "to_grid",   "grid_export", "Grid Exported"),
    # Solar & Load
    "solar_generated":    MetricSpec("solar_generated", "solar", "solar_generated", "Solar Generated"),
    "home_usage":         MetricSpec("home_usage",      "home",  "home_usage",      "Home Usage"),
    # Battery energy in/out
    "battery_charged":    MetricSpec("battery_charged",    "to_pw",   "battery_charged",    "Battery Charged"),
    "battery_discharged": MetricSpec("battery_discharged", "from_pw", "battery_discharged", "Battery Discharged"),
}