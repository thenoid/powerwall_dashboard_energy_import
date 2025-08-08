# Changelog

## 0.3.0 — 2025-08-08
- **Options Flow**: choose daily kWh boundary and data source
  - Day boundary: `local_midnight` (default), `rolling_24h`, `influx_daily_cq`
  - Series source: `autogen.http` (default) or `raw.http`
  - (CQ TZ remains configurable in options for future use)
- Sensors now honor these options for daily totals.
- Instantaneous kW logic unchanged from 0.2.1 (W→kW and magnitude).

## 0.2.1
- Fix instantaneous power units and magnitude.

## 0.2.0
- HA constants hotfix, changelog, release workflow.

## 0.1.0
- Initial release.
