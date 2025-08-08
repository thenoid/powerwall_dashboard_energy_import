# Changelog

## 0.4.0 — 2025-08-08
- **Built-in Daily and Monthly kWh sensors** (no Utility Meter helpers needed):
  - Home Usage, Solar Generated, Grid Imported/Exported, Battery Charged/Discharged
  - New entities end with `(Daily)` and `(Monthly)`.
- Honors Options:
  - If **Influx Daily CQ** is selected, Daily uses `daily.http` LAST(), Monthly sums `daily.http` since month start.
  - Otherwise, integrates from **local midnight** / **first of month** in your selected series (`autogen.http` or `raw.http`).

## 0.3.0
- Options flow for day boundary and series source.

## 0.2.1
- Fix instantaneous power units and magnitude.

## 0.2.0
- HA constants hotfix, changelog, release workflow.

## 0.1.0
- Initial release.
