## 0.5.6 — 2025-08-17
### Fixed
- Restore valid Python modules (remove stray `...` placeholders) in `__init__.py`, `sensor.py`, `backfill.py`, and `influx_client_backfill.py` so CI can run.
- Update CI to use `home-assistant/actions/hassfest@master` (was invalid reference) and add explicit HACS validation job.
- Lint: keep `ruff`/`black` jobs, fix unused imports + syntax.
- Tests: ensure Home Assistant is installed in CI before running pytest.

### Notes
- This is a CI/packaging fix; backfill logic remains a stub and will be completed in a subsequent minor release.

## 0.5.5 — 2025-08-17
### Fixed
- Ruff: repair broken import tuple in __init__.py; organize imports; remove unused imports.
- Modernize typing in influx_client.py; replace timezone.utc with datetime.UTC across codebase.
- Move ruff `ignore`/`select` to `[tool.ruff.lint]` as per deprecation warning.
# Changelog

## 0.4.4 — 2025-08-16
- All kWh sensors now use **state_class: total_increasing** to match Teslemetry and Energy Dashboard expectations.
  - Affects lifetime, (Daily), and (Monthly) sensors.
  - Prevents negative bars at midnight/month rollover.
  - After updating, open **Developer Tools → Statistics** and click **Fix** if any sensors are flagged.

## 0.4.3
- Config entry migration + custom Powerwall Name support.
