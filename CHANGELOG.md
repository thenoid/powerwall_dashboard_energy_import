## 0.5.2 — 2025-08-17
### Fixed
- HACS validation: add proper `hacs.json` and keep HA-only keys in `manifest.json`.
- Bump integration version to 0.5.2.

# Changelog

## 0.4.4 — 2025-08-16
- All kWh sensors now use **state_class: total_increasing** to match Teslemetry and Energy Dashboard expectations.
  - Affects lifetime, (Daily), and (Monthly) sensors.
  - Prevents negative bars at midnight/month rollover.
  - After updating, open **Developer Tools → Statistics** and click **Fix** if any sensors are flagged.

## 0.4.3
- Config entry migration + custom Powerwall Name support.
