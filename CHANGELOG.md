# Changelog

## 0.17.1 — 2026-01-13
- Add signed battery and grid power sensors for HA +/- power support
- Signed values are calculated as `from_pw - to_pw` (battery) and `from_grid - to_grid` (grid)

## 0.13.0 — 2026-01-03
- **CRITICAL FIX**: Sensors now report cumulative totals from InfluxDB beginning instead of daily/monthly resets
- **Breaking Change**: This fixes HA recorder confusion that caused cascading spikes and ancient baseline fallbacks
- **What changed**: `_daily` and `_monthly` sensors now properly implement `TOTAL_INCREASING` behavior (always increasing values)
- **Migration**: After upgrading, delete all statistics for affected sensors and run backfill service to rebuild from InfluxDB
- **Why**: Previous implementation reported daily totals (0-120 kWh) which HA's recorder interpreted as meter resets, causing it to fall back to ancient baselines (e.g., values from May/November 2025)
- **Impact**: Eliminates midnight spike problem permanently - sensors now work correctly with HA's statistics recorder

## 0.12.1 — 2026-01-02
- **Cleanup**: Removed misleading "auto-repair" references from code comments and documentation
- **Clarification**: Hour-range backfill parameters (`start_hour`, `end_hour`) are now clearly labeled as "Manual Surgical Repair" features
- The hour-range backfill feature remains functional and useful for manually fixing specific problematic hours
- Note: Automatic repair attempts were never implemented; the offline `fix_energy_dashboard_spikes.py` script is the supported solution for boundary spike repairs

## 0.4.4 — 2025-08-16
- All kWh sensors now use **state_class: total_increasing** to match Teslemetry and Energy Dashboard expectations.
  - Affects lifetime, (Daily), and (Monthly) sensors.
  - Prevents negative bars at midnight/month rollover.
  - After updating, open **Developer Tools → Statistics** and click **Fix** if any sensors are flagged.

## 0.4.3
- Config entry migration + custom Powerwall Name support.
