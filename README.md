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

**Recommended: Pause-and-Complete Backfill** (prevents data corruption):
```yaml
action: powerwall_dashboard_energy_import.backfill_from_date_to_now
data:
  start: "2024-01-01"          # Backfill from this date to current time
  sensor_prefix: "Powerwall"   # Optional: target specific integration
```

📝 **Expected Behavior**: You may see a one-time MySQL duplicate key error in the logs after running this service. This is normal and indicates successful operation - it occurs when the backfill includes the current hour and Home Assistant's recorder later tries to compile the same hourly statistics. The error is harmless and prevents boundary discontinuities.

**Advanced: Full Control Backfill**:
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
  overwrite_existing: false    # Optional: append mode (default)
  clear_short_term: false      # Optional: clear 5-min stats (keeps latest row)
  repair_short_term_baseline: false  # Optional: align short-term baseline to long-term
```

### Key Differences
- **`backfill_from_date_to_now`**: Automatically pauses live sensors during backfill to prevent baseline corruption. **Recommended for most users**.
- **`backfill`**: Full control over date ranges and overwrite behavior. Use when you need specific date ranges or overwrite mode.

⚠️ **Warning**: This directly modifies the recorder database. Use with caution and backup your database first.

### Troubleshooting
- **"No new statistics to import"**: Check InfluxDB has data for the specified date range
- **Massive energy spikes**: Use `backfill_from_date_to_now` instead of `backfill` to prevent baseline corruption
- **MySQL duplicate key error**: Expected one-time error when backfill includes current hour. This indicates successful operation - backfill imported statistics for the current hour, then Home Assistant's normal recorder tried to create the same hourly statistics. The error is harmless, won't repeat on subsequent runs, and confirms no boundary discontinuities occurred.
- **Missing Spook error**: Install the Spook integration - standard HA statistics API can't import data for entities with state_class
- **Service not found**: Restart Home Assistant after installation

## Database Repair Tool (First-Time Setup)

### Why This Is Needed

When you first install this integration and run the backfill service, Home Assistant's `TOTAL_INCREASING` sensor logic can detect discontinuities between the backfilled historical data and the live sensor data. This triggers HA's "meter reset detection," which causes massive spikes (5,000+ kWh jumps) in the Energy Dashboard.

**The Problem:**
1. You install the integration → Live sensors start from zero
2. You run backfill → Historical data gets imported
3. Home Assistant detects the discontinuity → Creates massive spikes in Energy Dashboard
4. Auto-healing inside the integration isn't possible (HA processes the discontinuity immediately)

**The Solution:** Repair the database directly while Home Assistant is stopped.

### First-Time Installation Workflow

**For new installations, follow this workflow to avoid Energy Dashboard spikes:**

1. **Install the integration** (Config Flow)
2. **Run the backfill service** to import historical data
3. **Stop Home Assistant**
4. **Backup your database:**
   ```bash
   mysqldump -u homeassistant -p ha_db > ha_backup_$(date +%Y%m%d).sql
   ```
5. **Run the database repair script** (see below)
6. **Restart Home Assistant** → Energy Dashboard shows correct values ✅

### Using the Repair Script

The `fix_energy_dashboard_spikes.py` script detects and repairs statistics that cause Energy Dashboard spikes.

**Step 1: Analyze (identify spikes)**
```bash
python3 fix_energy_dashboard_spikes.py \
  --mariadb-host 192.168.1.100 \
  --mariadb-user homeassistant \
  --mariadb-pass YOUR_PASSWORD \
  --mariadb-db homeassistant \
  --influx-host 192.168.1.100 \
  --influx-port 8087 \
  --influx-db powerwall \
  --sensor-prefix "7579_pwd" \
  --analyze 2025-11-15
```

**Step 2: Fix (repair identified spikes)**
```bash
python3 fix_energy_dashboard_spikes.py \
  --mariadb-host 192.168.1.100 \
  --mariadb-user homeassistant \
  --mariadb-pass YOUR_PASSWORD \
  --mariadb-db homeassistant \
  --influx-host 192.168.1.100 \
  --influx-port 8087 \
  --influx-db powerwall \
  --sensor-prefix "7579_pwd" \
  --fix 2025-11-15
```

**Required Parameters:**
- `--mariadb-host`: Home Assistant database host
- `--mariadb-user`: Database username (usually `homeassistant`)
- `--mariadb-pass`: Database password
- `--mariadb-db`: Database name (usually `homeassistant`)
- `--influx-host`: InfluxDB host (from powerwall-dashboard)
- `--influx-port`: InfluxDB port (default: `8087`)
- `--influx-db`: InfluxDB database name (usually `powerwall`)
- `--sensor-prefix`: Your Powerwall name/prefix (e.g., `7579_pwd` or `Powerwall`)

**Finding Your Sensor Prefix:**
```bash
# Connect to MariaDB
mysql -h HOST -u homeassistant -p homeassistant

# List all powerwall sensors
SELECT statistic_id FROM statistics_meta WHERE statistic_id LIKE '%powerwall%' LIMIT 5;

# Extract the prefix from sensor names like: sensor.7579_pwd_solar_generated_daily
# The prefix is the part between "sensor." and the sensor type (e.g., "7579_pwd")
```

### How It Works

The repair script:
1. **Detects spikes** by analyzing hour-to-hour jumps (e.g., >20 kWh battery charge per hour)
2. **Calculates correct values** from InfluxDB using cumulative integrals
3. **Updates corrupted statistics** with proper cumulative totals from InfluxDB
4. **Validates connections** before making any changes
5. **Requires explicit confirmation** with backup instructions

**Safety Features:**
- ✅ Connection validation before proceeding
- ✅ Explicit backup reminders
- ✅ Transaction control (rollback on error)
- ✅ Analyze mode (dry-run) to preview changes
- ✅ Detailed logging of all operations

### When to Use

**First-time setup:** Always use after initial backfill
**After Teslemetry migration:** Use if you see spikes after migrating
**Normal operation:** Not needed - only for initial setup or one-time migrations

## v0.13.0 Migration - Critical Fix for Midnight Spikes

### What Changed in v0.13.0

**CRITICAL BUG FIX**: Versions prior to 0.13.0 had a fundamental implementation error where `_daily` and `_monthly` sensors reported daily/monthly totals that reset at boundaries (0-120 kWh per day) instead of cumulative totals that always increase.

**The Problem:**
- Sensors were marked as `state_class: total_increasing` (telling Home Assistant they're cumulative meters)
- But they actually reported daily totals like `state=115 kWh` at 11 PM, then `state=5 kWh` at midnight
- Home Assistant's recorder detected this as a "meter reset" and fell back to ancient baselines (from May/November 2025)
- This caused cascading spikes in the Energy Dashboard every midnight

**The Fix:**
- Sensors now report true cumulative totals from InfluxDB beginning (always increasing values)
- Example: `state=11,957 kWh` at 11 PM, then `state=11,962 kWh` at midnight (+5 kWh)
- Home Assistant's recorder automatically calculates hourly/daily/monthly differences for Energy Dashboard display
- No more midnight spikes!

### Migration Required

**If you're upgrading from any version before 0.13.0, you MUST follow this procedure:**

**Step 1: Stop Home Assistant**
```bash
sudo systemctl stop home-assistant
```

**Step 2: Backup Your Database**
```bash
mysqldump -u homeassistant -p ha_db > ha_backup_$(date +%Y%m%d).sql
```

**Step 3: Run Cleanup Script**
This deletes all statistics for daily/monthly sensors (they'll be rebuilt from InfluxDB):
```bash
cd /path/to/powerwall_dashboard_energy_import
./cleanup_and_backfill.sh
```

The script will:
- Verify Home Assistant is stopped
- Delete all statistics for `*_daily` sensors
- Delete all statistics for `*_monthly` sensors
- Delete both long-term and short-term statistics
- Confirm successful cleanup

**Step 4: Start Home Assistant**
```bash
sudo systemctl start home-assistant
```

Wait for Home Assistant to fully start (check logs: `journalctl -fu home-assistant`)

**Step 5: Rebuild Statistics from InfluxDB**
In Home Assistant Developer Tools → Services:
```yaml
service: powerwall_dashboard_energy_import.backfill
data:
  all: true
  overwrite_existing: false
```

**Step 6: Monitor**
- Watch the Energy Dashboard for 24+ hours
- Midnight rollover should now be smooth (no spikes)
- Sensor values should continuously increase (never reset)

### Why This Approach Works

Home Assistant's `TOTAL_INCREASING` sensors work like odometers:
- ✅ **Correct**: State always increases (11,957 → 11,962 → 11,968 kWh)
- ❌ **Wrong**: State resets periodically (115 → 5 → 23 kWh) ← old behavior

Home Assistant's recorder compiles hourly statistics by calculating differences between consecutive states:
```
Hour 1: state_end=11,962, state_start=11,957 → sum_increase = 5 kWh
Hour 2: state_end=11,968, state_start=11,962 → sum_increase = 6 kWh
```

The Energy Dashboard shows these hourly/daily/monthly differences, NOT the raw sensor states.

### Troubleshooting

**Q: I still see spikes after migration**
- Verify you deleted BOTH `statistics` and `statistics_short_term` tables
- Check that backfill completed successfully (no errors in logs)
- Ensure you're running v0.13.0 (check `manifest.json`)

**Q: My sensor values look huge now**
- This is correct! They're cumulative totals from InfluxDB beginning
- Example: `sensor.powerwall_home_usage_daily` might show 11,957 kWh
- Energy Dashboard will still show daily usage (e.g., 23 kWh today)

**Q: Can I skip the migration if I don't have spikes?**
- No - the bug affects ALL versions before 0.13.0
- Spikes may appear during future HA updates or database operations
- Migration ensures long-term stability

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
