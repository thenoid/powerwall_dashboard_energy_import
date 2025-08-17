## 0.5.1 — 2025-08-17
### Added
- Backfill service `powerwall_dashboard_energy_import.backfill` (Influx→HA long_term via `async_add_external_statistics`).
- Supports start/end/all/metrics/dry_run/chunk_hours. Idempotent and chunked.

# Changelog

## 0.4.4 — 2025-08-16
- All kWh sensors now use **state_class: total_increasing** to match Teslemetry and Energy Dashboard expectations.
  - Affects lifetime, (Daily), and (Monthly) sensors.
  - Prevents negative bars at midnight/month rollover.
  - After updating, open **Developer Tools → Statistics** and click **Fix** if any sensors are flagged.

## 0.4.3
- Config entry migration + custom Powerwall Name support.
