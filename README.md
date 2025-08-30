# Powerwall Dashboard Energy Import (Home Assistant)

A custom Home Assistant integration that pulls **Tesla Powerwall** telemetry from an **InfluxDB 1.8.x** database populated by [powerwall-dashboard](https://github.com/jasonacox/powerwall-dashboard) and exposes Teslemetry-style sensors.

## About This Project

🔗 **Independent Community Project**: This integration is not affiliated with, endorsed by, or connected to Tesla, Teslemetry, Spook, or Home Assistant. It's a community-driven project built by advanced users for advanced users.

⭐ **Teslemetry is Excellent**: We highly recommend the official [Teslemetry integration](https://www.home-assistant.io/integrations/teslemetry/) for most users. It's professionally maintained, officially supported, and provides real-time cloud data directly from Tesla's fleet API.

🛠️ **For Powerwall Dashboard Users**: This integration serves a specific niche - advanced users already running [powerwall-dashboard](https://github.com/jasonacox/powerwall-dashboard) who want to leverage their existing InfluxDB infrastructure for Home Assistant energy monitoring. If you're not already using powerwall-dashboard, **use Teslemetry instead**.

- **HACS-compatible** custom integration
- **Config Flow**: set host, port, database, username, password (no YAML)
- **Teslemetry behavior**: daily totals are computed **since local midnight** via `integral()` in InfluxQL; instantaneous values use `LAST()`
- **Diagnostics** panel exposes last queries (redacts secrets)

## Installation

### Via HACS (Custom Repository)
1. In HACS → **Integrations** → ⋮ → **Custom repositories**: add your repo URL and category **Integration**.
2. Install **Powerwall Dashboard Energy Import**.
3. Restart Home Assistant.

### Manual
Copy the `custom_components/powerwall_dashboard_energy_import/` folder into your HA `custom_components/` directory and restart.

## Configuration
1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Powerwall Dashboard Energy Import**.
3. Enter your InfluxDB **Host**, **Port** (default `8086`), **Database** (e.g., `powerwall`), and optional **Username/Password**.
4. On success, sensors appear under the device **"Powerwall Dashboard (InfluxDB)"**.

## Backfill Service
Import historical statistics from InfluxDB into Home Assistant's Energy Dashboard:

### Prerequisites
**Requires [Spook integration](https://github.com/frenck/spook)** for `recorder.import_statistics` service. Install via:
- HACS: Search for "Spook 👻"  
- Manual: https://github.com/frenck/spook

### Usage
```yaml
action: powerwall_dashboard_energy_import.backfill
data:
  all: true                    # Import all available history
  sensor_prefix: "7579 PowerWall"  # Optional: target specific integration
```

Or import specific date range:
```yaml
action: powerwall_dashboard_energy_import.backfill
data:
  start: "2024-01-01"
  end: "2024-12-31"
```

⚠️ **Warning**: This directly modifies the recorder database. Use with caution and backup your database first.

## Teslemetry Migration
Migrate historical energy statistics from Teslemetry to preserve your Energy Dashboard data:

### Prerequisites
**Requires [Spook integration](https://github.com/frenck/spook)** for `recorder.import_statistics` service. Install via:
- HACS: Search for "Spook 👻"  
- Manual: https://github.com/frenck/spook

### Migration Workflow
1. **Install this integration** alongside your existing Teslemetry setup
2. **Run InfluxDB backfill** (optional) for deep historical data
3. **Test with dry run**:
   ```yaml
   action: powerwall_dashboard_energy_import.migrate_from_teslemetry
   data:
     dry_run: true
   ```
4. **Run full migration**:
   ```yaml
   action: powerwall_dashboard_energy_import.migrate_from_teslemetry
   data:
     auto_discover: true
   ```
5. **Switch Energy Dashboard** from Teslemetry entities to ours when ready
6. **Keep or remove Teslemetry** per your preference

### Migration Options
```yaml
# Auto-discovery mode (recommended)
action: powerwall_dashboard_energy_import.migrate_from_teslemetry
data:
  auto_discover: true
  start_date: "2023-01-01"  # Optional: limit migration scope
  dry_run: false

# Auto-discovery with custom entity prefixes
action: powerwall_dashboard_energy_import.migrate_from_teslemetry
data:
  auto_discover: true
  entity_prefix: "my_home"     # For entities like sensor.my_home_solar_generated
  sensor_prefix: "pw085"       # Target specific integration instance
  dry_run: false

# Manual entity mapping
action: powerwall_dashboard_energy_import.migrate_from_teslemetry  
data:
  auto_discover: false
  entity_mapping:
    sensor.tesla_site_home_energy: sensor.powerwall_dashboard_home_usage_daily
    sensor.tesla_site_solar_energy: sensor.powerwall_dashboard_solar_generated_daily
```

### Benefits
- ✅ **No data loss**: Original Teslemetry statistics preserved
- ✅ **Complete history**: Works with InfluxDB backfill for full timeline
- ✅ **Safe transition**: Gradual migration with rollback capability  
- ✅ **Smart discovery**: Automatically finds energy entities to migrate
- ✅ **Flexible targeting**: Support for custom entity prefixes and multiple integration instances
- ✅ **Production ready**: Successfully tested with 50,000+ statistics entries

⚠️ **Warning**: This copies statistics data. Backup your Home Assistant database first.

## Sensors
- **Battery Charged (kWh)** — integral of `to_pw` (positive) since midnight.
- **Battery Discharged (kWh)** — integral of `from_pw` (positive) since midnight.
- **Grid Exported (kWh)** — integral of `to_grid` (positive) since midnight.
- **Grid Imported (kWh)** — integral of `from_grid` (positive) since midnight.
- **Home Usage (kWh)** — integral of `home` since midnight.
- **Solar Generated (kWh)** — integral of `solar` since midnight.
- **Battery Power (kW)** — last of `to_pw` (proxy for charge power) and `from_pw` (discharge) reflected via state.
- **Grid Power (kW)** — last of `from_grid` (consumption) or `to_grid` (export) reflected via state.
- **Load Power (kW)** — last of `home` instantaneous.
- **Solar Power (kW)** — last of `solar` instantaneous.
- **Battery % Charged (%)** — last of `percentage`.
- **Tesla Battery State** — Charging / Discharging / Idle.
- **Tesla Power Grid State** — Producing / Consuming / Idle.
- **Island Status** — On-grid / Off-grid.

> These map to your `autogen.http` and `grid.http` measurements as produced by the powerwall-dashboard CQs.

## Diagnostics
From the integration card, choose **Download diagnostics** to get:
- Connection info (host/port/db; secrets redacted)
- The **last 20 InfluxQL queries** run by the integration

## Development
- Python 3.12+ recommended
- Linting: **ruff**

```bash
pip install ruff
ruff check custom_components
```

## License
MIT — see [LICENSE](LICENSE).

---

**Icon** is available at `custom_components/powerwall_dashboard_energy_import/assets/icon.svg`.
