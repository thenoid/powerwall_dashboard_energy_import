#!/usr/bin/env python3

"""
Fix Energy Dashboard Spikes - Database Repair Tool

This script repairs Home Assistant Energy Dashboard spikes caused by TOTAL_INCREASING
sensor discontinuities when backfilling historical data.

IMPORTANT: This script UPDATES the Home Assistant database directly.
          Always backup your database before running with --fix mode.

How it works:
1. Detects hour-to-hour jumps that exceed reasonable thresholds
2. Calculates correct cumulative values from InfluxDB
3. Updates corrupted statistics with proper values

Usage workflow:
1. Stop Home Assistant
2. Backup your database: mysqldump -u USER -p DATABASE > backup.sql
3. Run script in analyze mode to identify spikes
4. Run script in fix mode to repair identified spikes
5. Start Home Assistant
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

import mysql.connector
import requests  # type: ignore[import-untyped]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class EnergyDashboardSpikeFixer:
    def __init__(
        self,
        mariadb_config: dict[str, str],
        influx_config: dict[str, str],
        sensor_prefix: str,
    ):
        self.mariadb_config = mariadb_config
        self.influx_config = influx_config
        self.sensor_prefix = sensor_prefix

    def validate_connections(self) -> bool:
        """Validate both MariaDB and InfluxDB connections before proceeding."""
        logger.info("Validating database connections...")

        # Test MariaDB connection
        try:
            with self.get_mariadb_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
            logger.info("✓ MariaDB connection successful")
        except mysql.connector.Error as e:
            logger.error(f"✗ MariaDB connection failed: {e}")
            logger.error(
                f"  Check host={self.mariadb_config['host']}, user={self.mariadb_config['user']}, database={self.mariadb_config['database']}"
            )
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected MariaDB error: {e}")
            return False

        # Test InfluxDB connection
        try:
            url = (
                f"http://{self.influx_config['host']}:{self.influx_config['port']}/ping"
            )
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            logger.info("✓ InfluxDB connection successful")
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ InfluxDB connection failed: {e}")
            logger.error(
                f"  Check host={self.influx_config['host']}, port={self.influx_config['port']}"
            )
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected InfluxDB error: {e}")
            return False

        logger.info("✓ All database connections validated")
        return True

    def get_mariadb_connection(self):
        """Get MariaDB database connection."""
        try:
            return mysql.connector.connect(
                host=self.mariadb_config["host"],
                user=self.mariadb_config["user"],
                password=self.mariadb_config["password"],
                database=self.mariadb_config["database"],
                autocommit=False,  # Explicit transaction control
            )
        except mysql.connector.Error as e:
            logger.error(f"Failed to connect to MariaDB: {e}")
            raise

    def find_spike_statistics(
        self, date: str
    ) -> list[tuple[int, str, str, float, float]]:
        """Find statistics that cause Energy Dashboard spikes by detecting large jumps."""
        with self.get_mariadb_connection() as conn:
            cursor = conn.cursor()

            # Get all daily statistics for the date, ordered by time
            query = """
                SELECT
                    s.id,
                    sm.statistic_id,
                    FROM_UNIXTIME(s.start_ts) as hour_start,
                    s.sum,
                    LAG(s.sum) OVER (PARTITION BY sm.statistic_id ORDER BY s.start_ts) as prev_sum
                FROM statistics_meta sm
                JOIN statistics s ON sm.id = s.metadata_id
                WHERE sm.statistic_id LIKE %s
                AND DATE(FROM_UNIXTIME(s.start_ts)) = %s
                ORDER BY sm.statistic_id, s.start_ts
            """
            cursor.execute(query, (f"%{self.sensor_prefix}%daily%", date))
            results = cursor.fetchall()

        spikes = []
        for stat_id, statistic_id, hour_start, sum_val, prev_sum in results:
            if prev_sum is not None:
                # Calculate the hourly increase
                hourly_increase = sum_val - prev_sum

                # Detect unreasonable hourly increases that indicate Energy Dashboard spikes
                # These thresholds are for detecting the massive jumps caused by HA reset detection
                max_reasonable_hourly = {
                    "battery_charged_daily": 20,  # Max 20 kWh battery charge per hour
                    "battery_discharged_daily": 20,  # Max 20 kWh battery discharge per hour
                    "grid_imported_daily": 50,  # Max 50 kWh grid import per hour
                    "grid_exported_daily": 30,  # Max 30 kWh grid export per hour
                    "home_usage_daily": 50,  # Max 50 kWh home usage per hour
                    "solar_generated_daily": 30,  # Max 30 kWh solar generation per hour
                }

                # Check if this statistic type has unreasonable hourly change (positive OR negative)
                for sensor_type, max_hourly in max_reasonable_hourly.items():
                    if sensor_type in statistic_id:
                        # Detect massive positive spikes OR massive negative drops
                        if hourly_increase > max_hourly:
                            spikes.append(
                                (
                                    stat_id,
                                    statistic_id,
                                    hour_start,
                                    sum_val,
                                    hourly_increase,
                                )
                            )
                            logger.info(
                                f"POSITIVE SPIKE: {statistic_id} at {hour_start} jumped +{hourly_increase:.3f} kWh (max reasonable: {max_hourly} kWh)"
                            )
                            break
                        elif hourly_increase < -max_hourly:
                            spikes.append(
                                (
                                    stat_id,
                                    statistic_id,
                                    hour_start,
                                    sum_val,
                                    hourly_increase,
                                )
                            )
                            logger.info(
                                f"NEGATIVE SPIKE: {statistic_id} at {hour_start} dropped {hourly_increase:.3f} kWh (max reasonable drop: -{max_hourly} kWh)"
                            )
                            break

        return spikes

    def get_influx_cumulative_value(
        self, sensor_type: str, end_datetime: datetime
    ) -> float:
        """Get correct cumulative value from InfluxDB for a specific sensor type up to a given time.

        CRITICAL: This calculates cumulative totals since sensor start (for TOTAL_INCREASING),
        NOT daily totals since midnight!
        """
        # Map sensor types to InfluxDB fields
        field_mapping = {
            "battery_charged_daily": "to_pw",
            "battery_discharged_daily": "from_pw",
            "grid_imported_daily": "from_grid",
            "grid_exported_daily": "to_grid",
            "home_usage_daily": "home",
            "solar_generated_daily": "solar",
        }

        field = field_mapping.get(sensor_type)
        if not field:
            logger.warning(f"Unknown sensor type: {sensor_type}")
            return 0.0

        # Calculate cumulative value from earliest available data to the given hour
        # This is for TOTAL_INCREASING sensors which maintain cumulative totals since start
        end_iso = end_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Query fields directly, just like the sensor does (sensor.py:354-400)
        # CRITICAL: Must use autogen.http retention policy to match sensor behavior
        query = f"""
            SELECT integral({field})/1000/3600 as cumulative_value
            FROM autogen.http
            WHERE time < '{end_iso}'
            AND {field} > 0
        """

        try:
            url = f"http://{self.influx_config['host']}:{self.influx_config['port']}/query"
            params = {"db": self.influx_config["database"], "q": query}

            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if "results" in data and data["results"] and "series" in data["results"][0]:
                value = data["results"][0]["series"][0]["values"][0][1]
                return float(value or 0)
            else:
                logger.warning(f"No InfluxDB data for {sensor_type} at {end_datetime}")
                return 0.0

        except Exception as e:
            logger.error(f"Error querying InfluxDB for {sensor_type}: {e}")
            return 0.0

    def get_influx_hourly_increase(
        self, sensor_type: str, start_datetime: datetime, end_datetime: datetime
    ) -> float:
        """Get the hourly increase from InfluxDB for a specific hour range."""
        # Map sensor types to InfluxDB fields
        field_mapping = {
            "battery_charged_daily": "to_pw",
            "battery_discharged_daily": "from_pw",
            "grid_imported_daily": "from_grid",
            "grid_exported_daily": "to_grid",
            "home_usage_daily": "home",
            "solar_generated_daily": "solar",
        }

        field = field_mapping.get(sensor_type)
        if not field:
            logger.warning(f"Unknown sensor type: {sensor_type}")
            return 0.0

        start_iso = start_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Special handling for home usage (calculated field)
        if field == "home":
            query = f"""
                SELECT integral(from_grid)/1000/3600 + integral(from_pw)/1000/3600 + integral(solar)/1000/3600
                     - integral(to_grid)/1000/3600 - integral(to_pw)/1000/3600 as hourly_increase
                FROM http
                WHERE time >= '{start_iso}' AND time < '{end_iso}'
                AND (from_grid > 0 OR from_pw > 0 OR solar > 0 OR to_grid > 0 OR to_pw > 0)
            """
        elif field == "solar":
            query = f"""
                SELECT integral(solar)/1000/3600 as hourly_increase
                FROM http
                WHERE time >= '{start_iso}' AND time < '{end_iso}'
                AND solar > 0
            """
        else:
            query = f"""
                SELECT integral({field})/1000/3600 as hourly_increase
                FROM http
                WHERE time >= '{start_iso}' AND time < '{end_iso}'
                AND {field} > 0
            """

        try:
            url = f"http://{self.influx_config['host']}:{self.influx_config['port']}/query"
            params = {"db": self.influx_config["database"], "q": query}

            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if "results" in data and data["results"] and "series" in data["results"][0]:
                value = data["results"][0]["series"][0]["values"][0][1]
                return float(value or 0)
            else:
                logger.warning(
                    f"No InfluxDB data for {sensor_type} hourly increase {start_datetime} to {end_datetime}"
                )
                return 0.0

        except Exception as e:
            logger.error(
                f"Error querying InfluxDB for {sensor_type} hourly increase: {e}"
            )
            return 0.0

    def recalculate_all_statistics(self, start_date: str, end_date: str) -> bool:
        """Recalculate ALL statistics for a date range to fix HA recorder confusion.

        This rebuilds a consistent statistics chain by recalculating every sum value
        from InfluxDB beginning, eliminating any ancient baseline fallbacks that
        cause cascading spikes.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Recalculating ALL statistics from {start_date} to {end_date}...")
        logger.info("This will rebuild consistent statistics chain from InfluxDB data")

        # Parse dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Calculate total days
        total_days = (end_dt - start_dt).days + 1
        logger.info(f"Processing {total_days} days of statistics...")

        # Track statistics updated
        total_stats_updated = 0

        # Process each date in range
        current_dt = start_dt
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            logger.info(f"Processing date: {date_str}")

            try:
                with self.get_mariadb_connection() as conn:
                    cursor = conn.cursor()

                    # Get ALL statistics for this date, ordered by time
                    query = """
                        SELECT
                            s.id,
                            sm.statistic_id,
                            s.start_ts,
                            FROM_UNIXTIME(s.start_ts) as hour_start,
                            s.sum as old_sum
                        FROM statistics_meta sm
                        JOIN statistics s ON sm.id = s.metadata_id
                        WHERE sm.statistic_id LIKE %s
                        AND DATE(FROM_UNIXTIME(s.start_ts)) = %s
                        ORDER BY sm.statistic_id, s.start_ts
                    """
                    cursor.execute(query, (f"%{self.sensor_prefix}%daily%", date_str))
                    results = cursor.fetchall()

                    if not results:
                        logger.info(f"  No statistics found for {date_str}")
                        current_dt += timedelta(days=1)
                        continue

                    logger.info(f"  Found {len(results)} statistics to recalculate")

                    # Process each statistic
                    for (
                        stat_id,
                        statistic_id,
                        start_ts,
                        _hour_start,
                        old_sum,
                    ) in results:
                        # Determine sensor type from statistic_id
                        sensor_type = None
                        for stype in [
                            "battery_charged_daily",
                            "battery_discharged_daily",
                            "grid_imported_daily",
                            "grid_exported_daily",
                            "home_usage_daily",
                            "solar_generated_daily",
                        ]:
                            if stype in statistic_id:
                                sensor_type = stype
                                break

                        if not sensor_type:
                            logger.warning(
                                f"  Could not determine sensor type for {statistic_id}"
                            )
                            continue

                        # Calculate correct cumulative value from InfluxDB beginning
                        # This is the TOTAL since sensor start, not just since midnight
                        # CRITICAL: sum represents cumulative total at END of hour, not start
                        hour_dt = datetime.fromtimestamp(start_ts) + timedelta(hours=1)
                        correct_cumulative = self.get_influx_cumulative_value(
                            sensor_type, hour_dt
                        )

                        # Update the statistic with recalculated cumulative value
                        # Handle NULL old_sum values (treat as needing update)
                        should_update = (
                            old_sum is None or abs(correct_cumulative - old_sum) > 0.001
                        )

                        if should_update:
                            cursor.execute(
                                "UPDATE statistics SET sum = %s WHERE id = %s",
                                (correct_cumulative, stat_id),
                            )
                            total_stats_updated += 1

                            if total_stats_updated % 100 == 0:
                                logger.info(
                                    f"  Updated {total_stats_updated} statistics so far..."
                                )

                    conn.commit()
                    logger.info(f"  Completed {date_str}")

            except Exception as e:
                logger.error(f"Error processing date {date_str}: {e}")
                return False

            current_dt += timedelta(days=1)

        logger.info(
            f"Successfully recalculated {total_stats_updated} statistics across {total_days} days"
        )
        logger.info("Statistics chain rebuilt from consistent InfluxDB data")
        return True

    def fix_spikes(self, date: str) -> bool:
        """Fix Energy Dashboard spikes by correcting problematic statistics with proper values."""
        logger.info(f"Fixing Energy Dashboard spikes for {date}...")

        # Find spike statistics
        spikes = self.find_spike_statistics(date)

        if not spikes:
            logger.info(f"No Energy Dashboard spikes detected for {date}")
            return True

        logger.info(f"Found {len(spikes)} spike statistics to correct")

        try:
            with self.get_mariadb_connection() as conn:
                cursor = conn.cursor()

                for (
                    stat_id,
                    statistic_id,
                    hour_start,
                    sum_val,
                    hourly_increase,
                ) in spikes:
                    # hour_start is already a datetime object from MySQL
                    if isinstance(hour_start, str):
                        hour_dt = datetime.strptime(hour_start, "%Y-%m-%d %H:%M:%S")
                    else:
                        hour_dt = hour_start

                    # Determine sensor type from statistic_id
                    sensor_type = None
                    for stype in [
                        "battery_charged_daily",
                        "battery_discharged_daily",
                        "grid_imported_daily",
                        "grid_exported_daily",
                        "home_usage_daily",
                        "solar_generated_daily",
                    ]:
                        if stype in statistic_id:
                            sensor_type = stype
                            break

                    if not sensor_type:
                        logger.warning(
                            f"Could not determine sensor type for {statistic_id}"
                        )
                        continue

                    # Get correct cumulative value from InfluxDB
                    correct_value = self.get_influx_cumulative_value(
                        sensor_type, hour_dt
                    )

                    # Get the previous value to establish proper cumulative baseline
                    cursor.execute(
                        """
                        SELECT s.sum FROM statistics s
                        JOIN statistics_meta sm ON s.metadata_id = sm.id
                        WHERE sm.statistic_id = %s
                        AND s.start_ts < %s
                        ORDER BY s.start_ts DESC
                        LIMIT 1
                    """,
                        (statistic_id, hour_dt.timestamp()),
                    )

                    prev_result = cursor.fetchone()
                    if prev_result:
                        # Add the correct hourly increase to previous cumulative value
                        prev_cumulative = prev_result[0]
                        # Calculate ONLY the hourly increase from InfluxDB for this specific hour
                        hour_start_dt = hour_dt.replace(
                            minute=0, second=0, microsecond=0
                        )
                        prev_hour_dt = hour_start_dt - timedelta(hours=1)

                        # Get hourly increase from InfluxDB (NOT cumulative totals)
                        hourly_increase_influx = self.get_influx_hourly_increase(
                            sensor_type, prev_hour_dt, hour_start_dt
                        )
                        corrected_value = prev_cumulative + hourly_increase_influx
                    else:
                        # No previous value - this shouldn't happen for existing sensors
                        logger.warning(
                            f"No previous statistic found for {statistic_id}"
                        )
                        corrected_value = correct_value

                    logger.info(f"Correcting spike: {statistic_id} at {hour_start}")
                    logger.info(
                        f"  Old value: {sum_val:.3f} kWh (change: {hourly_increase:.3f} kWh)"
                    )
                    logger.info(f"  New value: {corrected_value:.3f} kWh")

                    # Update the statistic with the correct value
                    cursor.execute(
                        "UPDATE statistics SET sum = %s WHERE id = %s",
                        (corrected_value, stat_id),
                    )

                conn.commit()
                logger.info(f"Successfully corrected {len(spikes)} spike statistics")

        except Exception as e:
            logger.error(f"Error correcting spike statistics: {e}")
            return False

        logger.info(
            "Energy Dashboard spikes fixed with correct values. No restart needed."
        )
        return True

    def analyze_spikes(self, date: str) -> list[tuple[int, str, str, float, float]]:
        """Analyze and report Energy Dashboard spikes without fixing them."""
        logger.info(f"Analyzing Energy Dashboard spikes for {date}...")
        spikes = self.find_spike_statistics(date)

        if not spikes:
            logger.info(f"No Energy Dashboard spikes detected for {date}")
        else:
            logger.info(f"Found {len(spikes)} spike statistics")

        return spikes


def main():  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Fix Energy Dashboard spikes caused by Home Assistant TOTAL_INCREASING reset detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze spikes for a specific date
  %(prog)s --mariadb-host 192.168.0.25 --mariadb-user homeassistant --mariadb-pass mypass \\
           --mariadb-db ha_db --influx-host 192.168.0.10 --influx-db powerwall \\
           --sensor-prefix 7579_pwd --analyze 2025-09-19

  # Fix spikes for a specific date
  %(prog)s --mariadb-host 192.168.0.25 --mariadb-user homeassistant --mariadb-pass mypass \\
           --mariadb-db ha_db --influx-host 192.168.0.10 --influx-db powerwall \\
           --sensor-prefix 7579_pwd --fix 2025-09-19

  # Recalculate ALL statistics for date range (fixes HA recorder confusion)
  %(prog)s --mariadb-host 192.168.0.25 --mariadb-user homeassistant --mariadb-pass mypass \\
           --mariadb-db ha_db --influx-host 192.168.0.10 --influx-db powerwall \\
           --sensor-prefix 7579_pwd --fix-range 2025-05-06 2026-01-02
        """,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--analyze",
        metavar="DATE",
        help="Analyze Energy Dashboard spikes for date (YYYY-MM-DD)",
    )
    mode_group.add_argument(
        "--fix",
        metavar="DATE",
        help="Fix Energy Dashboard spikes for date (YYYY-MM-DD)",
    )
    mode_group.add_argument(
        "--fix-range",
        nargs=2,
        metavar=("START_DATE", "END_DATE"),
        help="Recalculate ALL statistics for date range (YYYY-MM-DD YYYY-MM-DD) - fixes HA recorder confusion",
    )

    # MariaDB connection parameters
    parser.add_argument("--mariadb-host", required=True, help="MariaDB/MySQL host")
    parser.add_argument("--mariadb-user", required=True, help="MariaDB/MySQL username")
    parser.add_argument("--mariadb-pass", required=True, help="MariaDB/MySQL password")
    parser.add_argument(
        "--mariadb-db", required=True, help="MariaDB/MySQL database name"
    )

    # InfluxDB connection parameters
    parser.add_argument("--influx-host", required=True, help="InfluxDB host")
    parser.add_argument(
        "--influx-port", default="8087", help="InfluxDB port (default: 8087)"
    )
    parser.add_argument("--influx-db", required=True, help="InfluxDB database name")

    # Sensor configuration
    parser.add_argument(
        "--sensor-prefix", required=True, help='Sensor prefix (e.g., "7579_pwd")'
    )

    args = parser.parse_args()

    # Validate date format
    if args.fix_range:
        start_date, end_date = args.fix_range
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid date format (expected YYYY-MM-DD)")
            sys.exit(1)
    else:
        date = args.analyze or args.fix
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid date format: {date} (expected YYYY-MM-DD)")
            sys.exit(1)

    # Build configuration
    mariadb_config = {
        "host": args.mariadb_host,
        "user": args.mariadb_user,
        "password": args.mariadb_pass,
        "database": args.mariadb_db,
    }

    influx_config = {
        "host": args.influx_host,
        "port": args.influx_port,
        "database": args.influx_db,
    }

    # Create fixer instance
    fixer = EnergyDashboardSpikeFixer(mariadb_config, influx_config, args.sensor_prefix)

    # Validate connections before proceeding
    if not fixer.validate_connections():
        logger.error("Connection validation failed. Please check your configuration.")
        sys.exit(1)

    try:
        if args.analyze:
            logger.info(f"Analyzing Energy Dashboard for date: {date}")
            spikes = fixer.analyze_spikes(date)
            sys.exit(0 if not spikes else 1)
        elif args.fix_range:
            # Safety confirmation for date range fix
            start_date, end_date = args.fix_range
            print("\n" + "=" * 70)
            print("⚠️  WARNING: BULK DATABASE MODIFICATION")
            print("=" * 70)
            print(
                f"This will RECALCULATE ALL statistics from {start_date} to {end_date}."
            )
            print(
                "Every statistic sum will be rebuilt from InfluxDB cumulative totals."
            )
            print(
                "This fixes HA recorder confusion by creating a consistent statistics chain."
            )
            print()
            print("IMPORTANT:")
            print("  1. Make sure Home Assistant is STOPPED")
            print("  2. Backup your database first:")
            print(
                f"     mysqldump -u {args.mariadb_user} -p {args.mariadb_db} > ha_backup_{start_date}_to_{end_date}.sql"
            )
            print("  3. You can restore from backup if needed:")
            print(
                f"     mysql -u {args.mariadb_user} -p {args.mariadb_db} < ha_backup_{start_date}_to_{end_date}.sql"
            )
            print()
            print("This operation will process ALL statistics in the date range,")
            print("not just detected spikes. This ensures a consistent chain.")
            print("=" * 70)
            print()

            confirm = (
                input(
                    "Have you backed up your database and want to proceed? (yes/NO): "
                )
                .lower()
                .strip()
            )
            if confirm != "yes":
                logger.info("Operation cancelled - backup and retry when ready")
                sys.exit(0)

            success = fixer.recalculate_all_statistics(start_date, end_date)
            if success:
                logger.info("✓ Date range recalculation completed successfully")
                logger.info("✓ Statistics chain rebuilt from consistent InfluxDB data")
                logger.info("You can now restart Home Assistant")
            sys.exit(0 if success else 1)
        elif args.fix:
            # Safety confirmation
            print("\n" + "=" * 70)
            print("⚠️  WARNING: DATABASE MODIFICATION")
            print("=" * 70)
            print(
                f"This will UPDATE statistics in your Home Assistant database for {date}."
            )
            print(
                "Corrupted statistics will be replaced with correct values from InfluxDB."
            )
            print()
            print("IMPORTANT:")
            print("  1. Make sure Home Assistant is STOPPED")
            print("  2. Backup your database first:")
            print(
                f"     mysqldump -u {args.mariadb_user} -p {args.mariadb_db} > ha_backup_{date}.sql"
            )
            print("  3. You can restore from backup if needed:")
            print(
                f"     mysql -u {args.mariadb_user} -p {args.mariadb_db} < ha_backup_{date}.sql"
            )
            print("=" * 70)
            print()

            confirm = (
                input(
                    "Have you backed up your database and want to proceed? (yes/NO): "
                )
                .lower()
                .strip()
            )
            if confirm != "yes":
                logger.info("Operation cancelled - backup and retry when ready")
                sys.exit(0)

            success = fixer.fix_spikes(date)
            if success:
                logger.info("✓ Repair completed successfully")
                logger.info("You can now restart Home Assistant")
            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
