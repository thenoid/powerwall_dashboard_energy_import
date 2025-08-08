# Powerwall Dashboard Energy Import (Home Assistant)

A custom Home Assistant integration that pulls **Tesla Powerwall** telemetry from an **InfluxDB 1.8.x** database populated by [powerwall-dashboard](https://github.com/jasonacox/powerwall-dashboard) and exposes Teslemetry-style sensors.

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
