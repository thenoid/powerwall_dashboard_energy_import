# Backfill Service Enhancement Plan

## Problem Statement
Both the **backfill service** and **Teslemetry migration service** only process sensors ending with `_daily` suffix. While daily sensors are working correctly, we need to ADD the missing sensor types for complete historical data coverage:
1. ✅ **Daily sensors** (`sensor.7579_pwd_grid_imported_daily`) - ALREADY WORKING  
2. ❌ **Main sensors** (`sensor.7579_pwd_grid_imported`) - MISSING from both services
3. ❌ **Monthly sensors** (`sensor.7579_pwd_grid_imported_monthly`) - MISSING from both services

## Current State Analysis
### Backfill Service (`BACKFILL_FIELDS`)
- ✅ **Daily sensors working**: Hard-coded mapping includes `_daily` sensors
- ❌ **Main sensors missing**: No entries for main sensors (e.g., `home_usage`, `solar_generated`)
- ❌ **Monthly sensors missing**: No entries for monthly sensors (e.g., `home_usage_monthly`)

### Teslemetry Migration Service (`our_entity_patterns`)
- ✅ **Daily sensors working**: All patterns map to `_daily` sensors  
- ❌ **Main sensors missing**: No mappings to main sensors
- ❌ **Monthly sensors missing**: No mappings to monthly sensors

## Sensor Type Differences
### 1. Main Sensor (`kwh_total` mode)
- **Purpose**: Real-time cumulative total energy since integration started
- **Data Source**: Direct InfluxDB queries with `integral()` function
- **State Class**: `TOTAL_INCREASING` (true cumulative counter)
- **Backfill Need**: Historical cumulative statistics for proper totals

### 2. Daily Sensor (`kwh_daily` mode) 
- **Purpose**: Energy for current day only (resets at midnight)
- **Data Source**: InfluxDB queries from day start (`midnight_local`)
- **State Class**: `TOTAL_INCREASING` (resets daily)
- **Backfill Need**: Daily statistics for Energy Dashboard

### 3. Monthly Sensor (`kwh_monthly` mode)
- **Purpose**: Energy for current month only (resets monthly)  
- **Data Source**: InfluxDB queries from month start (`month_start_local`)
- **State Class**: `TOTAL_INCREASING` (resets monthly)
- **Backfill Need**: Monthly energy analysis and trends

## Proposed Solution
Expand **BOTH services** to include the TWO missing sensor types:

### Backfill Service Updates (`BACKFILL_FIELDS`)
- ✅ Daily sensors: `"home_usage_daily": "home"` (already working)
- ➕ **Add** Main sensors: `"home_usage": "home"` 
- ➕ **Add** Monthly sensors: `"home_usage_monthly": "home"`

### Teslemetry Migration Service Updates (`our_entity_patterns`)
- ✅ Daily sensors: `"home": "home_usage_daily"` (already working)
- ➕ **Add** Main sensors: `"home": "home_usage"` (additional mapping)
- ➕ **Add** Monthly sensors: `"home": "home_usage_monthly"` (additional mapping)

This will provide complete historical data coverage across all sensor types for both migration paths.

## Implementation Plan

### 1. Analyze Current Sensor Filtering Logic
- [x] Locate the current filtering code in `__init__.py`
- [x] Understand how sensors are identified and filtered
- [x] Document the current behavior

### 2. Update Both Service Configurations
#### Backfill Service (`BACKFILL_FIELDS`)
- [x] Add main sensor entries: `"home_usage": "home"`, `"solar_generated": "solar"`, etc.
- [x] Add monthly sensor entries: `"home_usage_monthly": "home"`, `"solar_generated_monthly": "solar"`, etc.
- [x] Keep existing daily entries for backward compatibility

#### Teslemetry Migration Service (`our_entity_patterns`) 
- [x] Add main sensor mappings for each energy type
- [x] Add monthly sensor mappings for each energy type  
- [x] Update priority patterns to handle multiple sensor types
- [x] Maintain backward compatibility with existing daily mappings

### 3. Test-Driven Development (Following CLAUDE.md Requirements)
- [x] **Update/add tests FIRST** before implementing changes
- [x] Run tests to verify they fail (red)
- [x] Create unit tests for both services:
  - [x] **Backfill Service Tests**: Test BACKFILL_FIELDS includes main/monthly sensors
  - [x] **Teslemetry Migration Tests**: Test our_entity_patterns maps to all sensor types  
  - [x] Test main sensor detection (`sensor.prefix_field`)
  - [x] Test daily sensor detection (`sensor.prefix_field_daily`) 
  - [x] Test monthly sensor detection (`sensor.prefix_field_monthly`)
  - [x] Test mixed sensor type processing in both services
- [ ] Verify no regressions in existing functionality
- [ ] Ensure backfill works correctly for each sensor type
- [ ] **Target: Maintain >90% code coverage**

### 4. Implementation
- [ ] Implement minimal code to make tests pass (green)
- [ ] Ensure all sensor types are processed by backfill service

### 5. Full CI Validation Suite (Mandatory per CLAUDE.md)
- [x] **pytest with coverage**: `python -m pytest tests/ -v --cov=custom_components --cov-report=term-missing`
- [x] **Type checking**: `mypy .`
- [x] **Code formatting**: `ruff check .` and `ruff format --check .`
- [x] **Security scan**: `bandit -r custom_components/`
- [x] **Dependency scan**: `safety scan`  
- [x] **Import compatibility**: Test all imports work correctly
- [x] **Fix any issues** discovered by the validation suite

### 6. Version Management
- [ ] Update version number following SEMVER
- [ ] Update manifest.json

### 7. Real Data Validation
- [ ] Test with real data to ensure all three sensor types are processed
- [ ] Verify statistics are correctly generated for main, daily, and monthly sensors
- [ ] Confirm Energy Dashboard continues to work with daily sensors
- [ ] Verify main sensors show proper cumulative totals
- [ ] Check monthly sensors provide correct month-to-date values

## Technical Considerations
- The backfill logic should work identically for all three sensor types (main, daily, monthly)
- Need to ensure the statistics metadata is correctly configured for all sensor types
- Current day limiting logic should apply to all sensor types
- Database continuity must be maintained for all sensor types
- Main sensors require true cumulative statistics (never reset)
- Daily sensors require daily-resetting statistics (reset at midnight)
- Monthly sensors require monthly-resetting statistics (reset at month start)

## Risk Assessment
- Low risk change since it's expanding functionality rather than changing existing logic
- Main risk is processing more data than intended, but this is the desired behavior
- Backup existing statistics before testing with real data

## Success Criteria
- [ ] Backfill service processes all three sensor types:
  - [ ] `sensor.7579_pwd_grid_imported` (main/cumulative)
  - [ ] `sensor.7579_pwd_grid_imported_daily` (daily reset)  
  - [ ] `sensor.7579_pwd_grid_imported_monthly` (monthly reset)
- [ ] All three sensor types show correct historical statistics in Home Assistant
- [ ] Energy Dashboard continues to work properly with daily sensors
- [ ] Main sensors show proper cumulative totals without resets
- [ ] Monthly sensors show correct month-to-date values
- [ ] No performance degradation or errors introduced
- [ ] All existing tests continue to pass (>90% coverage maintained)
- [ ] New tests validate the expanded functionality for all sensor types
- [ ] Full CI validation suite passes (pytest, mypy, ruff, bandit, safety)
- [ ] No type errors, linting issues, or security vulnerabilities