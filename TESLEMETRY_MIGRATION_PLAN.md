# Teslemetry Statistics Migration Plan

## Executive Summary

This document outlines a comprehensive approach for migrating historical energy statistics from Teslemetry to our custom Powerwall Dashboard Energy Import integration. The solution preserves all existing data while providing users with complete historical continuity through a dedicated migration service.

## Problem Statement

When users switch from Teslemetry to our custom integration, they lose all historical Energy Dashboard data because Home Assistant ties statistics to specific entity IDs. This creates a significant barrier to adoption since users lose valuable long-term energy monitoring data.

### User Input & Requirements
- **No entity ID takeover**: User explicitly rejected risky approaches that modify existing Teslemetry entity IDs
- **Preserve existing data**: All Teslemetry historical statistics must remain intact
- **Work with InfluxDB backfill**: Must complement our existing Spook-powered historical backfill from InfluxDB
- **Safe transition**: Users should be able to gradually migrate without risk

## Research Findings

### Home Assistant Statistics Architecture
Based on research from [Home Assistant Data Science Portal](https://data.home-assistant.io/docs/statistics/):

- **Statistics Tables**: 
  - `statistics_meta`: Metadata about data sources
  - `statistics_short_term`: 5-minute data aggregates (purged after 10 days)
  - `statistics`: Hourly data aggregates (permanently stored)
- **Entity Requirements**: Entities need `state_class: total_increasing`, `device_class: energy`, `unit_of_measurement: kWh`

### Migration Approaches Research
From [Home Assistant Community discussions](https://community.home-assistant.io/t/migrate-energy-statistics-from-one-entity-to-another/405863):

1. **Entity ID Replacement** (HA 2023.4+): Delete old entity, rename new entity to match
2. **Database Migration**: Direct SQL queries to transfer statistics between metadata IDs
3. **Statistics Copy**: Extract via `recorder.get_statistics`, import via Spook's `recorder.import_statistics`

### Teslemetry Entity Structure
Research from [Teslemetry documentation](https://www.home-assistant.io/integrations/teslemetry/):

- **Entity Format**: `sensor.{site_name}_{sensor_type}`
- **Key Energy Entities**: 
  - `sensor.{site_name}_grid_power` (requires template conversion to energy)
  - `sensor.{site_name}_solar_power` (requires template conversion to energy)
  - `sensor.{site_name}_battery_power` (requires template conversion to energy)
- **Template Sensors**: Users often create Riemann sum integrations to convert power (kW) to energy (kWh)

### Available Tools
- **`recorder.get_statistics`**: Official HA service to extract historical statistics
- **`recorder.import_statistics`**: Spook service for importing historical data
- **No Export Service**: No official `recorder.export_statistics` exists

## Recommended Solution: Statistics Copy Migration

### Core Strategy
Implement a **dedicated migration service** that copies all Teslemetry historical statistics into our integration's entities using different entity IDs, preserving original data while providing complete historical continuity.

### Technical Architecture

#### Phase 1: Statistics Extraction Service
Create `powerwall_dashboard_energy_import.migrate_from_teslemetry` service that:

1. **Auto-discovery**: Scan entity registry for Teslemetry energy entities
   - Identify entities with `state_class: total_increasing` 
   - Filter for Tesla/energy-related entity names
   - Handle template sensors created for Energy Dashboard

2. **Data Extraction**: Use `recorder.get_statistics` to retrieve historical data
   - Extract long-term statistics (hourly aggregates)
   - Handle time range specification
   - Manage large dataset pagination

3. **Entity Mapping**: Map Teslemetry entities to our integration entities
   ```
   sensor.tesla_site_home_energy → sensor.powerwall_dashboard_home_usage_daily
   sensor.tesla_site_solar_energy → sensor.powerwall_dashboard_solar_generated_daily
   sensor.tesla_site_battery_energy_in → sensor.powerwall_dashboard_battery_charged_daily
   sensor.tesla_site_battery_energy_out → sensor.powerwall_dashboard_battery_discharged_daily
   sensor.tesla_site_grid_energy_in → sensor.powerwall_dashboard_grid_imported_daily
   sensor.tesla_site_grid_energy_out → sensor.powerwall_dashboard_grid_exported_daily
   ```

#### Phase 2: Data Processing & Transformation
4. **Format Conversion**: Transform `recorder.get_statistics` output to Spook import format
   - Convert timestamps to ISO format
   - Ensure proper sum/mean/min/max structure
   - Handle timezone alignment

5. **Data Validation**: Comprehensive integrity checks
   - Detect temporal gaps in data
   - Identify and flag anomalous spikes
   - Validate units and value ranges
   - Check for overlapping periods with InfluxDB data

6. **Deduplication Logic**: Merge overlapping datasets intelligently
   - Prioritize InfluxDB data over Teslemetry (more granular)
   - Fill gaps with Teslemetry data
   - Handle boundary conditions at overlap edges

#### Phase 3: Import via Spook Integration
7. **Batch Import**: Use existing Spook `recorder.import_statistics` service
   - Import to our entity IDs (maintaining separation)
   - Preserve original Teslemetry entities untouched
   - Comprehensive error handling and rollback capability

8. **Progress Tracking**: User-friendly migration monitoring
   - Detailed logging of migration progress
   - Error reporting with actionable feedback
   - Dry-run capability for validation

### Service Interface

#### Migration Service Parameters
```yaml
action: powerwall_dashboard_energy_import.migrate_from_teslemetry
data:
  # Auto-discovery mode (default)
  auto_discover: true
  
  # Manual entity mapping (optional override)
  entity_mapping:
    sensor.tesla_home_energy: sensor.powerwall_dashboard_home_usage_daily
    sensor.tesla_solar_energy: sensor.powerwall_dashboard_solar_generated_daily
  
  # Time range (optional - defaults to all available data)
  start_date: "2023-01-01"
  end_date: "2024-12-31"
  
  # Migration options
  dry_run: false  # Validate without importing
  overwrite_existing: false  # Skip if our entities already have data
  merge_strategy: "prioritize_influx"  # or "prioritize_teslemetry"
```

#### Error Handling & Safety
- **Spook Validation**: Verify Spook availability before starting
- **Backup Recommendation**: Guide users to backup HA database
- **Rollback Capability**: Provide method to undo migration if needed
- **Data Integrity Verification**: Post-migration validation checks

### Integration with Existing Features

#### Complementary with InfluxDB Backfill
- **Deep History**: InfluxDB backfill provides years of historical data
- **Recent Gap Filling**: Teslemetry migration fills period between InfluxDB and present
- **Single Timeline**: Both import to same entity IDs for unified experience
- **Smart Merging**: Deduplication logic prevents overlapping data issues

#### User Workflow
1. **Install Integration**: Set up real-time sensors
2. **InfluxDB Backfill**: Import deep historical data (years back)
3. **Teslemetry Migration**: Fill recent gaps and provide continuity
4. **Energy Dashboard Switch**: Gradually transition from Teslemetry entities to ours
5. **Optional Cleanup**: Keep or remove Teslemetry per user preference

## Implementation Plan

### Milestone 1: Core Migration Service
- [ ] Implement entity auto-discovery logic
- [ ] Build `recorder.get_statistics` extraction
- [ ] Create data transformation pipeline
- [ ] Integrate with existing Spook import functionality

### Milestone 2: Advanced Features
- [ ] Add deduplication and merge logic
- [ ] Implement comprehensive validation
- [ ] Build dry-run and progress tracking
- [ ] Create rollback capabilities

### Milestone 3: User Experience
- [ ] Add comprehensive error handling and logging
- [ ] Create user documentation and guides
- [ ] Implement migration status reporting
- [ ] Add post-migration verification tools

### Milestone 4: Testing & Documentation
- [ ] Unit tests for all migration components
- [ ] Integration tests with mock Teslemetry data
- [ ] User acceptance testing scenarios
- [ ] Complete documentation update

## Benefits of This Approach

### Technical Benefits
- ✅ **Zero Risk**: No modification of existing Teslemetry data
- ✅ **Complete History**: InfluxDB + Teslemetry + live data continuity
- ✅ **Flexible Timeline**: Users control migration timing
- ✅ **Rollback Safety**: Original data always preserved
- ✅ **Smart Integration**: Works with existing backfill features

### User Experience Benefits
- ✅ **Gradual Transition**: Can compare both integrations during migration
- ✅ **No Data Loss**: All historical information preserved
- ✅ **One-Click Migration**: Simple service call handles complexity
- ✅ **Clear Documentation**: Step-by-step migration guidance
- ✅ **Validation Tools**: Dry-run and verification capabilities

### Maintenance Benefits
- ✅ **Clean Architecture**: Separate concerns, single responsibility
- ✅ **Testable Components**: Each phase independently testable
- ✅ **Extensible Design**: Easy to support other integrations in future
- ✅ **Observable Operations**: Comprehensive logging and monitoring

## Risks and Mitigations

### Technical Risks
- **Large Dataset Performance**: Mitigate with batch processing and progress tracking
- **Memory Usage**: Stream processing for large statistics sets
- **Database Conflicts**: Comprehensive validation before import
- **Spook Dependencies**: Clear error messaging when Spook unavailable

### User Experience Risks
- **Migration Complexity**: Provide clear documentation and dry-run options
- **Data Corruption Fears**: Emphasize non-destructive approach in messaging
- **Time Investment**: Set proper expectations about migration duration

## Success Metrics

### Technical Metrics
- Migration completes without data loss
- All historical timestamps preserved accurately
- No duplicate statistics created
- Performance acceptable for typical datasets

### User Experience Metrics
- Clear migration instructions and documentation
- Successful user testimonials
- Minimal support requests about migration process
- Smooth Energy Dashboard transition experience

## Conclusion

This migration approach provides a comprehensive, safe, and user-friendly solution for transitioning from Teslemetry to our custom integration. By copying statistics rather than replacing entities, we eliminate risk while providing complete historical continuity. The integration with our existing InfluxDB backfill creates a powerful combination that gives users the most complete energy monitoring dataset possible.

The phased implementation approach allows for iterative development and testing, ensuring a robust and reliable migration experience for all users.