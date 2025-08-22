DOMAIN = "powerwall_dashboard_energy_import"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_DB_NAME = "database"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# User-friendly Powerwall name
CONF_PW_NAME = "pw_name"
DEFAULT_PW_NAME = "Powerwally McPowerwall Face"

# Options
OPT_DAY_MODE = "day_mode"  # local_midnight | rolling_24h | influx_daily_cq
OPT_SERIES_SOURCE = "series_source"  # autogen.http | raw.http
OPT_CQ_TZ = "cq_tz"  # e.g., America/Denver

# Defaults
DEFAULT_DAY_MODE = "local_midnight"
DEFAULT_SERIES_SOURCE = "autogen.http"
DEFAULT_CQ_TZ = "America/Denver"
