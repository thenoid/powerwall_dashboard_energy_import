## 0.5.4 — 2025-08-17
### Fixed
- Lint: address UP017 (use datetime.UTC), import order, and `%` string formatting in queries.
- HACS: use minimal `hacs.json` schema.

# Changelog

## 0.4.4 — 2025-08-16
- All kWh sensors now use **state_class: total_increasing** to match Teslemetry and Energy Dashboard expectations.
  - Affects lifetime, (Daily), and (Monthly) sensors.
  - Prevents negative bars at midnight/month rollover.
  - After updating, open **Developer Tools → Statistics** and click **Fix** if any sensors are flagged.

## 0.4.3
- Config entry migration + custom Powerwall Name support.
